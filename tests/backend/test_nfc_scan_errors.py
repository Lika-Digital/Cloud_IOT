"""
NFC /scan — distinct, actionable failures (v3.43, Rule 3 of the access-control plan)
===================================================================================

Four defects, and what they had in common: `/scan` answered **"pending — please plug in your
charger"**, or an indistinguishable error, in situations where nothing could follow.

| Was | Now |
|---|---|
| unknown tag **and** unresolvable pedestal both `404 "NFC tag not provisioned"` | 404 vs 500, different text |
| socket charging **and** a live pending scan both `409 "Socket already in use"` | two different 409 messages |
| smart mode OFF — **not checked at all** | 409, and it says to ask the marina office |
| pedestal not responding — **not checked at all** | 503, and it says to contact the marina office |

The last one is the most user-visible defect in the whole audit. Telling a customer "pending,
plug in your charger" when the NUC cannot act means they plug in, wait, nothing happens, and
blame the system rather than retrying. This cabinet was silent for 19 days in September.

Two properties these tests are built around:

* **Distinctness is asserted, not just failure.** Every case checks the status *and* that the
  message differs from its near neighbour. Asserting "not 200" would have passed on the
  original code for two of the four.
* **Liveness must not come from the database.** TC-NFCE-06 gives the cabinet a perfectly
  healthy-looking stored `last_heartbeat` and `opta_connected=1` while the in-memory heartbeat
  is stale, and requires the scan to fail anyway. A predicate a retained replay can satisfy is
  not a liveness check (`docs/engineering_notes.md`).

  TC-NFCE-01  unknown tag and unresolvable pedestal are told apart
  TC-NFCE-02  socket-in-use and pending-scan-held are told apart
  TC-NFCE-03  smart mode OFF refuses, in words a customer can act on
  TC-NFCE-04  a pedestal never heard from refuses
  TC-NFCE-05  a pedestal whose live heartbeat has gone stale refuses
  TC-NFCE-06  a healthy-looking DB row does NOT make a stale cabinet look reachable
  TC-NFCE-07  liveness is checked before smart mode
  TC-NFCE-08  every message is actionable — no bare codes, no jargon
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

ERP_KEY = "test-erp-key-scan-errors"
CAB = "TST_SCANERR_CAB"


@pytest.fixture(autouse=True)
def _erp_key():
    from app.config import settings
    prev = settings.erp_api_key
    settings.erp_api_key = ERP_KEY
    yield
    settings.erp_api_key = prev


def _erp() -> dict:
    return {"X-API-Key": ERP_KEY}


@pytest.fixture(scope="module")
def scan_pid(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig

    r = client.post("/api/pedestals/", json={
        "name": "Scan Errors Pedestal", "location": "Err Dock", "data_mode": "real",
    }, headers=auth_headers)
    pid = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.berth_ref = "VEZ_E1"
        cfg.provisioning_mode = "nfc"
        cfg.smart_mode = True
        for sid in (1, 2, 3, 4):
            if db.query(SocketConfig).filter(
                    SocketConfig.pedestal_id == pid,
                    SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=True))
        db.commit()
    finally:
        db.close()
    return pid


@pytest.fixture(autouse=True)
def _alive_and_smart(scan_pid):
    """Default every test to a healthy cabinet: live heartbeat, smart mode ON.

    Each test then breaks exactly one thing, so a failure names its own cause.
    """
    from app.services.mqtt_handlers import last_heartbeat

    _set_smart_mode(scan_pid, True)
    last_heartbeat[scan_pid] = datetime.utcnow()
    yield
    last_heartbeat.pop(scan_pid, None)


def _set_smart_mode(pid: int, on: bool) -> None:
    from app.models.pedestal_config import PedestalConfig

    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        cfg.smart_mode = on
        db.commit()
    finally:
        db.close()


def _clear(pid: int) -> None:
    from app.models.nfc_pending_session import NfcPendingSession
    from app.models.nfc_tag import NfcTag
    from app.models.session import Session

    db = _S()
    try:
        db.query(NfcPendingSession).delete()
        db.query(NfcTag).filter(NfcTag.cabinet_id.in_([CAB, "GHOST_CAB"])).delete()
        db.query(Session).filter(Session.pedestal_id == pid).delete()
        db.commit()
    finally:
        db.close()


def _provision(client, auth_headers, tag: str, socket: str = "Q1",
               cabinet: str = CAB) -> None:
    r = client.post("/api/nfc/tags", headers=auth_headers,
                    json={"cabinet_id": cabinet, "socket_id": socket, "nfc_tag_id": tag})
    assert r.status_code == 200, r.text


def _scan(client, tag: str) -> "object":
    return client.post("/api/nfc/scan", headers=_erp(),
                       json={"nfc_tag_id": tag, "user_id": "erp-scan-errors"})


# ═══ TC-NFCE-01 ══════════════════════════════════════════════════════════════

def test_tc_nfce_01_unknown_tag_vs_unresolvable_pedestal(client, auth_headers, scan_pid):
    """A tag nobody registered, and a tag registered to a cabinet we do not know.

    These shared a status AND a message, so a provisioning fault on our side was
    indistinguishable from a customer presenting a random card.
    """
    _clear(scan_pid)

    unknown = _scan(client, "NEVER-PROVISIONED")
    assert unknown.status_code == 404, unknown.text

    # A tag pointing at a cabinet with no pedestal row — our provisioning error.
    _provision(client, auth_headers, "GHOST-TAG", "Q1", cabinet="GHOST_CAB")
    ghost = _scan(client, "GHOST-TAG")

    assert ghost.status_code == 500, (
        f"a tag registered to an unknown cabinet returned {ghost.status_code}; it is a "
        f"server-side inconsistency, not an unknown tag"
    )
    assert ghost.json()["detail"] != unknown.json()["detail"], (
        "the two faults still share a message, so they remain indistinguishable:\n"
        f"  unknown tag: {unknown.json()['detail']}\n"
        f"  bad mapping: {ghost.json()['detail']}"
    )


# ═══ TC-NFCE-02 ══════════════════════════════════════════════════════════════

def test_tc_nfce_02_socket_in_use_vs_pending_held(client, auth_headers, scan_pid):
    """"Someone is charging" and "someone tapped 30 seconds ago" are minutes apart in what
    you should do, and they shared one message."""
    from app.models.session import Session

    _clear(scan_pid)
    _provision(client, auth_headers, "INUSE-TAG", "Q1")

    # Case A — an active session on that socket.
    db = _S()
    try:
        db.add(Session(pedestal_id=scan_pid, socket_id=1, type="electricity",
                       status="active", started_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()
    in_use = _scan(client, "INUSE-TAG")
    assert in_use.status_code == 409, in_use.text

    # Case B — no session, but a live pending scan holding the socket.
    _clear(scan_pid)
    _provision(client, auth_headers, "HELD-TAG", "Q1")
    first = _scan(client, "HELD-TAG")
    assert first.status_code == 200, first.text
    held = _scan(client, "HELD-TAG")
    assert held.status_code == 409, held.text

    assert held.json()["detail"] != in_use.json()["detail"], (
        "socket-in-use and pending-scan-held still share a message:\n"
        f"  in use: {in_use.json()['detail']}\n"
        f"  held:   {held.json()['detail']}"
    )
    # The hold expires, so saying when is what makes the message actionable.
    assert any(ch.isdigit() for ch in held.json()["detail"]), \
        "the held message should tell the customer until when, so waiting is a real option"


# ═══ TC-NFCE-03 ══════════════════════════════════════════════════════════════

def test_tc_nfce_03_smart_mode_off_refuses(client, auth_headers, scan_pid):
    """Smart mode OFF means the Opta ignores the NUC, so nothing can follow a scan."""
    _clear(scan_pid)
    _provision(client, auth_headers, "SMARTOFF-TAG", "Q1")
    _set_smart_mode(scan_pid, False)

    r = _scan(client, "SMARTOFF-TAG")
    assert r.status_code == 409, (
        f"smart mode OFF returned {r.status_code}: {r.text}. Before v3.43 this returned 200 "
        f"with 'please plug in your charger', and nothing would have happened."
    )
    detail = r.json()["detail"].lower()
    assert "marina" in detail, \
        f"the message must tell the customer who can help: {r.json()['detail']}"
    for jargon in ("smart mode", "smartmode", "opta", "mqtt", "standalone"):
        assert jargon not in detail, \
            f"{jargon!r} is engineer vocabulary and means nothing on a pontoon: {detail}"


# ═══ TC-NFCE-04 / 05 / 06 — liveness ═════════════════════════════════════════

def test_tc_nfce_04_never_heard_from_refuses(client, auth_headers, scan_pid):
    """No heartbeat since this backend started: we do not know the cabinet is there.

    Refusing is correct rather than pessimistic. "We have not heard from it" and "it is fine"
    are different claims, and only one of them is supported by evidence.
    """
    from app.services.mqtt_handlers import last_heartbeat

    _clear(scan_pid)
    _provision(client, auth_headers, "NOHB-TAG", "Q1")
    last_heartbeat.pop(scan_pid, None)

    r = _scan(client, "NOHB-TAG")
    assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"
    assert "marina" in r.json()["detail"].lower()


def test_tc_nfce_05_stale_heartbeat_refuses(client, auth_headers, scan_pid):
    """Heard from, but not recently enough — the same threshold the comm-loss watchdog uses."""
    from app.routers.nfc import COMM_LOSS_TIMEOUT_S
    from app.services.mqtt_handlers import last_heartbeat

    _clear(scan_pid)
    _provision(client, auth_headers, "STALE-TAG", "Q1")
    last_heartbeat[scan_pid] = datetime.utcnow() - timedelta(
        seconds=COMM_LOSS_TIMEOUT_S + 30)

    r = _scan(client, "STALE-TAG")
    assert r.status_code == 503, f"expected 503, got {r.status_code}: {r.text}"

    # ...and a fresh heartbeat lets it through again, so the check is not simply always-refuse.
    last_heartbeat[scan_pid] = datetime.utcnow()
    _clear(scan_pid)
    _provision(client, auth_headers, "FRESH-TAG", "Q1")
    assert _scan(client, "FRESH-TAG").status_code == 200


def test_tc_nfce_06_healthy_db_row_does_not_fake_liveness(client, auth_headers, scan_pid):
    """The v3.40 lesson, as a scan test.

    The cabinet's STORED state says reachable and recently seen — exactly what a retained MQTT
    replay produces after a backend restart — while the in-memory heartbeat, which only live
    traffic writes, is stale. The scan must believe the in-memory one.

    Without this the NFC path would repeat the bug the dashboard already had: a cabinet dead
    for weeks reported as online because its last stored message looked fine.
    """
    from app.models.pedestal_config import PedestalConfig
    from app.services.mqtt_handlers import last_heartbeat

    _clear(scan_pid)
    _provision(client, auth_headers, "FAKEALIVE-TAG", "Q1")

    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(
            PedestalConfig.pedestal_id == scan_pid).first()
        cfg.opta_connected = 1
        cfg.last_heartbeat = datetime.utcnow()      # looks perfectly healthy
        cfg.status = "online"
        db.commit()
    finally:
        db.close()

    last_heartbeat.pop(scan_pid, None)              # but nothing live has been heard

    r = _scan(client, "FAKEALIVE-TAG")
    assert r.status_code == 503, (
        f"got {r.status_code} — the scan trusted the stored heartbeat. That column survives a "
        f"restart and a retained replay writes it, so it is last-known state, never liveness."
    )


def test_tc_nfce_07_liveness_is_checked_before_smart_mode(client, auth_headers, scan_pid):
    """Both wrong at once: report the more fundamental fact.

    If the cabinet is not answering we cannot trust our stored view of its smart mode either,
    so "not responding" is the more truthful answer and the one that suggests the right action.
    """
    from app.services.mqtt_handlers import last_heartbeat

    _clear(scan_pid)
    _provision(client, auth_headers, "BOTHBAD-TAG", "Q1")
    _set_smart_mode(scan_pid, False)
    last_heartbeat.pop(scan_pid, None)

    r = _scan(client, "BOTHBAD-TAG")
    assert r.status_code == 503, (
        f"got {r.status_code}; with both faults present the liveness answer must win, because "
        f"the stored smart-mode value is not trustworthy for a cabinet that is not answering"
    )


# ═══ TC-NFCE-08 ══════════════════════════════════════════════════════════════

def test_tc_nfce_08_every_refusal_is_actionable(client, auth_headers, scan_pid):
    """No bare codes, no jargon, and something the customer can actually do.

    These strings are read by someone on a pontoon with a cable in their hand.
    """
    from app.services.mqtt_handlers import last_heartbeat

    collected = []

    _clear(scan_pid)
    collected.append(_scan(client, "STILL-UNKNOWN"))            # 404

    _provision(client, auth_headers, "ACT-GHOST", "Q1", cabinet="GHOST_CAB")
    collected.append(_scan(client, "ACT-GHOST"))                # 500

    _clear(scan_pid)
    _provision(client, auth_headers, "ACT-SMART", "Q1")
    _set_smart_mode(scan_pid, False)
    collected.append(_scan(client, "ACT-SMART"))                # 409
    _set_smart_mode(scan_pid, True)

    _clear(scan_pid)
    _provision(client, auth_headers, "ACT-DEAD", "Q1")
    last_heartbeat.pop(scan_pid, None)
    collected.append(_scan(client, "ACT-DEAD"))                 # 503

    for r in collected:
        detail = r.json()["detail"]
        assert len(detail) > 25, f"too terse to act on: {detail!r}"
        assert detail[0].isupper() and detail.rstrip().endswith("."), \
            f"not a sentence: {detail!r}"
        assert any(w in detail.lower() for w in ("marina", "another socket", "wait")), (
            f"no action offered, so the customer is left with nothing to do: {detail!r}"
        )

    statuses = [r.status_code for r in collected]
    assert len(set(statuses)) == len(statuses), \
        f"two different faults share a status code: {statuses}"
