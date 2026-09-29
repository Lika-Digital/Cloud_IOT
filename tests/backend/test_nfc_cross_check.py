"""
NFC tag/socket cross-check — double-bookkeeping (v3.43)
======================================================

Decisions 4 and 5 of the access-control plan.

ERP keeps its own tag→socket mapping and resolves the tag before calling us. We keep the same
mapping. **Two independent records of one fact mean a disagreement exposes an error that is
otherwise invisible** — a tag physically stuck on the wrong socket, two labels swapped at
installation, a wrong socket number typed into ERP. Without the check we switch the socket ERP
names and the customer pays for a neighbour's power, and nothing anywhere reports it.

Where it lives, and why it is not `/scan`: this is on the **activation path**, the call that
actually switches power. A mismatch on `/scan` costs nothing because `/scan` switches nothing, so
refusing there would be the strictness without the benefit.

The three cases are deliberately asymmetric. The cost of the design is maintaining the mapping
twice, so it must not fail hard everywhere:

| Case | Behaviour | Why |
|---|---|---|
| agree | act | — |
| disagree | **refuse + alarm** | installation and configuration have diverged; that needs a human, not a retry |
| no local mapping | **act**, log unverified | an incomplete local mapping must not stop a paying customer charging |

  TC-NFCX-01  agreement acts, and reports that it was verified
  TC-NFCX-02  disagreement refuses AND raises an alarm — power is not switched
  TC-NFCX-03  a tag we do not know acts anyway, and says it could not be verified
  TC-NFCX-04  no tag supplied is allowed during the optional phase
  TC-NFCX-05  once required, the ERP path must supply it...
  TC-NFCX-06  ...but a human at the dashboard is never required to
  TC-NFCX-07  the check applies to activate, not stop
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

CAB = "TST_XCHECK_CAB"
OTHER_CAB = "TST_XCHECK_OTHER"


@pytest.fixture(scope="module")
def xcheck_pid(client, auth_headers):
    """A smart-mode cabinet with all four sockets plugged in, so activation can proceed."""
    from app.models.pedestal_config import PedestalConfig, SocketState
    from app.models.socket_config import SocketConfig

    r = client.post("/api/pedestals/", json={
        "name": "CrossCheck Pedestal", "location": "XCheck Dock", "data_mode": "real",
    }, headers=auth_headers)
    pid = r.json()["id"]

    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.smart_mode = True
        for sid in (1, 2, 3, 4):
            if db.query(SocketConfig).filter(
                    SocketConfig.pedestal_id == pid,
                    SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=True))
            st = db.query(SocketState).filter(
                SocketState.pedestal_id == pid, SocketState.socket_id == sid).first()
            if st is None:
                db.add(SocketState(pedestal_id=pid, socket_id=sid, connected=True))
            else:
                st.connected = True
        db.commit()
    finally:
        db.close()
    return pid


@pytest.fixture(autouse=True)
def _clean(xcheck_pid):
    """Reset state, and point alarm_service at the test DB.

    `trigger_alarm` opens its own `SessionLocal` rather than taking the request's session, so
    without the patch the alarm lands in the real pedestal.db and the assertion sees nothing —
    which looks exactly like "no alarm was raised". Same approach as `test_temp_alarm.py`.
    """
    from app.config import settings
    from app.models.active_alarm import ActiveAlarm
    from app.models.nfc_tag import NfcTag

    prev = settings.nfc_cross_check_required
    settings.nfc_cross_check_required = False
    db = _S()
    try:
        db.query(NfcTag).filter(NfcTag.cabinet_id.in_([CAB, OTHER_CAB])).delete()
        db.query(ActiveAlarm).filter(
            ActiveAlarm.alarm_type == "nfc_mapping_mismatch").delete()
        db.commit()
    finally:
        db.close()
    with patch("app.services.alarm_service.SessionLocal", _S):
        yield
    settings.nfc_cross_check_required = prev


def _ext() -> dict:
    """Mimic the gateway's provenance header on a proxied ERP call."""
    from app.routers.external_api_gateway import EXT_API_CALLER_HEADER

    return {EXT_API_CALLER_HEADER: "1"}


def _provision(client, auth_headers, tag: str, socket: str, cabinet: str = CAB) -> None:
    r = client.post("/api/nfc/tags", headers=auth_headers,
                    json={"cabinet_id": cabinet, "socket_id": socket, "nfc_tag_id": tag})
    assert r.status_code == 200, r.text


def _activate(client, headers, pid: int, socket: str, tag: str | None = None,
              action: str = "activate"):
    body = {"action": action}
    if tag is not None:
        body["nfc_tag_id"] = tag
    return client.post(f"/api/controls/pedestal/{pid}/socket/{socket}/cmd",
                       headers=headers, json=body)


def _mismatch_alarms() -> list:
    from app.models.active_alarm import ActiveAlarm

    db = _S()
    try:
        return db.query(ActiveAlarm).filter(
            ActiveAlarm.alarm_type == "nfc_mapping_mismatch").all()
    finally:
        db.close()


# ═══ TC-NFCX-01 ══════════════════════════════════════════════════════════════

def test_tc_nfcx_01_agreement_acts_and_says_so(client, auth_headers, xcheck_pid):
    _provision(client, auth_headers, "XC-AGREE", "Q1")

    r = _activate(client, {**auth_headers, **_ext()}, xcheck_pid, "Q1", tag="XC-AGREE")
    assert r.status_code == 200, r.text
    assert r.json()["nfc_cross_check"] == "verified", (
        "ERP should be told its instruction was checked against our mapping, not merely "
        f"accepted: {r.json()}"
    )
    assert _mismatch_alarms() == []


# ═══ TC-NFCX-02 ══════════════════════════════════════════════════════════════

def test_tc_nfcx_02_disagreement_refuses_and_alarms(client, auth_headers, xcheck_pid):
    """The case the whole design exists for: a tag on the wrong socket.

    Refusing is not the only requirement — an alarm is, because a refusal ERP retries and
    nobody sees is a customer who cannot charge and a fault nobody investigates.
    """
    _provision(client, auth_headers, "XC-ON-Q1", "Q1")

    # ERP asks for Q3 while our mapping says Q1.
    r = _activate(client, {**auth_headers, **_ext()}, xcheck_pid, "Q3", tag="XC-ON-Q1")
    assert r.status_code == 409, f"a mapping mismatch must refuse, got {r.status_code}: {r.text}"

    detail = r.json()["detail"]
    assert "Q1" in detail and "Q3" in detail, \
        f"the refusal must name both sides so it can be diagnosed: {detail}"

    alarms = _mismatch_alarms()
    assert len(alarms) == 1, (
        f"expected exactly one nfc_mapping_mismatch alarm, got {len(alarms)}. A silent refusal "
        f"means nobody goes to look at the physical tag."
    )
    assert alarms[0].pedestal_id == xcheck_pid
    assert "XC-ON-Q1" in alarms[0].message
    assert alarms[0].severity == "critical"


# ═══ TC-NFCX-03 ══════════════════════════════════════════════════════════════

def test_tc_nfcx_03_unknown_tag_acts_but_reports_unverified(client, auth_headers,
                                                            xcheck_pid):
    """An incomplete local mapping must never stop a paying customer charging.

    This is the deliberate asymmetry: we cannot verify, so we trust ERP and record that we
    trusted it. Blocking here would turn our own missing configuration into the customer's
    problem.
    """
    r = _activate(client, {**auth_headers, **_ext()}, xcheck_pid, "Q2",
                  tag="XC-NEVER-PROVISIONED")
    assert r.status_code == 200, (
        f"an unknown tag must not block activation, got {r.status_code}: {r.text}"
    )
    assert r.json()["nfc_cross_check"] == "unverified"
    assert _mismatch_alarms() == [], \
        "an unverifiable tag is not a mismatch and must not raise the mismatch alarm"


# ═══ TC-NFCX-04 / 05 / 06 — the rollout ══════════════════════════════════════

def test_tc_nfcx_04_optional_phase_allows_no_tag(client, auth_headers, xcheck_pid):
    r = _activate(client, {**auth_headers, **_ext()}, xcheck_pid, "Q4")
    assert r.status_code == 200, r.text
    assert r.json()["nfc_cross_check"] == "not-supplied"


def test_tc_nfcx_05_required_phase_refuses_erp_without_a_tag(client, auth_headers,
                                                             xcheck_pid):
    """The date in `settings.nfc_cross_check_required` is what turns this on (2026-11-30)."""
    from app.config import settings

    settings.nfc_cross_check_required = True
    r = _activate(client, {**auth_headers, **_ext()}, xcheck_pid, "Q1")
    assert r.status_code == 400, (
        f"with the cross-check required, an ERP activation without nfc_tag_id must be refused, "
        f"got {r.status_code}: {r.text}"
    )
    assert "nfc_tag_id" in r.json()["detail"]


def test_tc_nfcx_06_required_phase_never_blocks_a_human(client, auth_headers, xcheck_pid):
    """An operator at the dashboard has no tag in hand and never will.

    Requiring one of them would break the marina's own controls to enforce a contract that is
    ERP's, which is why the requirement keys off the gateway's provenance header rather than
    applying to everyone.
    """
    from app.config import settings

    settings.nfc_cross_check_required = True
    # No _ext() header: this is the dashboard.
    r = _activate(client, auth_headers, xcheck_pid, "Q1")
    assert r.status_code == 200, (
        f"the dashboard was blocked by a requirement meant for ERP: {r.status_code} {r.text}"
    )
    assert r.json()["nfc_cross_check"] == "not-supplied"


# ═══ TC-NFCX-07 ══════════════════════════════════════════════════════════════

def test_tc_nfcx_07_stop_is_never_cross_checked(client, auth_headers, xcheck_pid):
    """A stop is always safe to honour, even with a disagreeing mapping.

    The worst case for an unnecessary stop is a session ending early. The worst case for
    refusing one is power left on when someone asked for it off, which is the more dangerous of
    the two — so the check applies to activation only.
    """
    from app.config import settings

    _provision(client, auth_headers, "XC-STOP", "Q1")
    settings.nfc_cross_check_required = True

    # Mismatched tag AND the required phase — a stop still goes through.
    r = _activate(client, {**auth_headers, **_ext()}, xcheck_pid, "Q3",
                  tag="XC-STOP", action="stop")
    assert r.status_code == 200, (
        f"a stop was refused over a mapping disagreement, leaving power on: {r.text}"
    )
    assert r.json()["nfc_cross_check"] == "not-applicable"
    assert _mismatch_alarms() == [], "a stop must not raise a mapping alarm"
