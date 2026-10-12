"""D6.1 (2026-10-12) — the ERP owns the NFC mapping and the customer; the cabinet measures.

What is new in this step and pinned here:

  TC-D61-01  electricity, the real path: POST /scan {cabinet_id, outlet, erp_ref} -> plug-in
             -> OutletActivated -> the session carries erp_ref, and GET /session returns it
  TC-D61-02  water, the real path: /scan V1 -> water/V1/cmd activate -> OutletActivated -> erp_ref
  TC-D61-03  GET /api/nfc/sessions refuses an incomplete query (400), never guesses
  TC-D61-04  by erp_ref: that reference's sessions only, active and ended, newest first
  TC-D61-05  by end time: [ended_from, ended_to) — from inclusive, to exclusive; active never in
  TC-D61-06  pages: total and next_offset; walking the pages drops nothing and repeats nothing
  TC-D61-07  reading GET /api/nfc/sessions has NO side effects (stamps nothing reconciled)
  TC-D61-08  the routes D6.1 commented out answer as absent

The /scan refusal rules (in use, held, smart mode, liveness, malformed outlet, unknown cabinet,
the pre-D6.1 body) are pinned in test_nfc_scan_errors.py and test_nfc_six_tag_model.py.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from conftest import TestSession as _S

ERP_KEY = "test-erp-key-d61"
CAB = "MAR_D61_TEST_01"


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
def pid(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig

    r = client.post("/api/pedestals/", json={
        "name": "D6.1 Pedestal", "location": "Dock D", "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    p = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == p).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=p)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.smart_mode = True
        cfg.provisioning_mode = "nfc"
        for sid in (1, 2, 3, 4):
            if db.query(SocketConfig).filter(SocketConfig.pedestal_id == p,
                                             SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=p, socket_id=sid, auto_activate=False))
        db.commit()
    finally:
        db.close()
    return p


@pytest.fixture(autouse=True)
def _alive(pid):
    from app.services.mqtt_handlers import last_heartbeat
    last_heartbeat[pid] = datetime.utcnow()
    yield
    last_heartbeat.pop(pid, None)


def _clear(p):
    from app.models.nfc_pending_session import NfcPendingSession
    from app.models.session import Session
    db = _S()
    try:
        db.query(NfcPendingSession).filter(NfcPendingSession.cabinet_id == CAB).delete()
        db.query(Session).filter(Session.pedestal_id == p).delete()
        db.commit()
    finally:
        db.close()


def _scan(client, outlet, erp_ref):
    return client.post("/api/nfc/scan", headers=_erp(),
                       json={"cabinet_id": CAB, "outlet": outlet, "erp_ref": erp_ref})


def _run(coro_fn, *args):
    """Run an MQTT event handler on a fresh DB session with broadcasts and webhooks muted."""
    with (
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
        patch("app.services.erp_webhook.post_erp_event", AsyncMock()),
        patch("app.services.mqtt_handlers._maybe_auto_activate", AsyncMock()),
    ):
        db = _S()
        try:
            asyncio.run(coro_fn(db, *args))
        finally:
            db.close()


def _active(p, socket_id, kind):
    from app.models.session import Session
    db = _S()
    try:
        s = (db.query(Session).filter(Session.pedestal_id == p, Session.socket_id == socket_id,
                                      Session.type == kind, Session.status == "active").first())
        return None if s is None else (s.id, s.erp_ref)
    finally:
        db.close()


# ═══ TC-D61-01 / 02 — the real paths ═════════════════════════════════════════

def test_tc_d61_01_electricity_scan_to_session_carries_erp_ref(client, pid):
    from app.services.mqtt_handlers import (
        _handle_event_outlet_activated, _handle_event_user_plugged_in)
    _clear(pid)
    r = _scan(client, "Q3", "ERP-REF-ELEC-1")
    assert r.status_code == 200, r.text
    assert r.json()["erp_ref"] == "ERP-REF-ELEC-1" and r.json()["status"] == "pending"

    _run(_handle_event_user_plugged_in, pid, "Q3", "POWER", {})
    _run(_handle_event_outlet_activated, pid, "Q3", "POWER", {})

    found = _active(pid, 3, "electricity")
    assert found is not None, "plug-in after a scan did not open a session"
    sid, erp_ref = found
    assert erp_ref == "ERP-REF-ELEC-1", f"the session carries erp_ref={erp_ref!r}"

    body = client.get(f"/api/nfc/session/{sid}", headers=_erp()).json()
    assert body["erp_ref"] == "ERP-REF-ELEC-1" and "customer_id" not in body
    _clear(pid)


def test_tc_d61_02_water_scan_to_session_carries_erp_ref(client, auth_headers, pid):
    from app.services.mqtt_handlers import _handle_event_outlet_activated
    _clear(pid)
    assert _scan(client, "V1", "ERP-REF-WATER-1").status_code == 200

    with patch("app.routers.controls.mqtt_service.publish"):
        r = client.post(f"/api/controls/pedestal/{pid}/water/V1/cmd",
                        json={"action": "activate"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    _run(_handle_event_outlet_activated, pid, "V1", "WATER", {})

    found = _active(pid, 1, "water")
    assert found is not None and found[1] == "ERP-REF-WATER-1", f"water session: {found}"
    _clear(pid)


# ═══ GET /api/nfc/sessions ═══════════════════════════════════════════════════

def _seed(p, erp_ref, *, ended_at=None, started_at=None, socket_id=1, status=None):
    from app.models.session import Session
    db = _S()
    try:
        s = Session(pedestal_id=p, socket_id=socket_id, type="electricity",
                    status=status or ("active" if ended_at is None else "completed"),
                    started_at=started_at or (ended_at or datetime.utcnow()) - timedelta(hours=1),
                    ended_at=ended_at, erp_ref=erp_ref, energy_kwh=1.0)
        db.add(s)
        db.commit()
        return s.id
    finally:
        db.close()


def _list(client, **params):
    return client.get("/api/nfc/sessions", headers=_erp(), params=params)


def test_tc_d61_03_an_incomplete_query_is_refused_not_guessed(client, pid):
    t = "2026-10-01T00:00:00Z"
    for params in ({}, {"ended_from": t}, {"ended_to": t},
                   {"ended_from": t, "ended_to": t},
                   {"ended_from": "2026-10-02T00:00:00Z", "ended_to": t}):
        r = _list(client, **params)
        assert r.status_code == 400, f"{params} -> {r.status_code}: {r.text}"
    assert client.get("/api/nfc/sessions", params={"erp_ref": "x"}).status_code == 401


def test_tc_d61_04_by_erp_ref_only_that_reference_newest_first(client, pid):
    _clear(pid)
    now = datetime.utcnow()
    old = _seed(pid, "REF-A", ended_at=now - timedelta(days=2), started_at=now - timedelta(days=3))
    live = _seed(pid, "REF-A", started_at=now - timedelta(minutes=5), socket_id=2)
    _seed(pid, "REF-B", ended_at=now - timedelta(days=1))

    body = _list(client, erp_ref="REF-A").json()
    assert [s["session_id"] for s in body["sessions"]] == [live, old]
    assert body["total"] == 2 and body["next_offset"] is None
    assert {s["erp_ref"] for s in body["sessions"]} == {"REF-A"}
    _clear(pid)


def test_tc_d61_05_end_window_is_from_inclusive_to_exclusive(client, pid):
    _clear(pid)
    lo = datetime(2026, 10, 1, 0, 0, 0)
    hi = datetime(2026, 10, 2, 0, 0, 0)
    at_lo = _seed(pid, "R", ended_at=lo)                              # IN  (inclusive)
    inside = _seed(pid, "R", ended_at=lo + timedelta(hours=12))       # IN
    at_hi = _seed(pid, "R", ended_at=hi)                              # OUT (exclusive)
    before = _seed(pid, "R", ended_at=lo - timedelta(seconds=1))      # OUT
    _seed(pid, "R")                                                   # active: never in a range

    body = _list(client, ended_from="2026-10-01T00:00:00Z", ended_to="2026-10-02T00:00:00Z").json()
    ids = [s["session_id"] for s in body["sessions"]]
    assert ids == [at_lo, inside], f"window returned {ids}"
    assert at_hi not in ids and before not in ids

    # The next window picks up exactly the boundary row the first one left out.
    nxt = _list(client, ended_from="2026-10-02T00:00:00Z", ended_to="2026-10-03T00:00:00Z").json()
    assert [s["session_id"] for s in nxt["sessions"]] == [at_hi]

    # Combined with erp_ref, both filters apply.
    both = _list(client, erp_ref="nobody", ended_from="2026-10-01T00:00:00Z",
                 ended_to="2026-10-02T00:00:00Z").json()
    assert both["total"] == 0
    _clear(pid)


def test_tc_d61_06_pages_drop_nothing_and_repeat_nothing(client, pid):
    _clear(pid)
    base = datetime(2026, 9, 1)
    # 7 sessions, two pairs sharing an end time so the id tie-break is exercised.
    ends = [base + timedelta(hours=h) for h in (1, 2, 2, 3, 4, 4, 5)]
    seeded = [_seed(pid, f"P{i}", ended_at=e, socket_id=(i % 4) + 1) for i, e in enumerate(ends)]

    seen, offset, pages = [], 0, 0
    while offset is not None:
        body = _list(client, ended_from="2026-09-01T00:00:00Z", ended_to="2026-09-02T00:00:00Z",
                     limit=3, offset=offset).json()
        assert body["total"] == 7
        seen += [s["session_id"] for s in body["sessions"]]
        offset = body["next_offset"]
        pages += 1
    assert pages == 3
    assert seen == sorted(seen, key=lambda i: (ends[seeded.index(i)], i)), "order not total"
    assert sorted(seen) == sorted(seeded) and len(seen) == len(set(seen)), (
        f"paging dropped or repeated rows: {seen}")
    _clear(pid)


def test_tc_d61_07_reading_the_list_has_no_side_effects(client, pid):
    from app.models.session import Session
    _clear(pid)
    sid = _seed(pid, "NO-STAMP", ended_at=datetime.utcnow() - timedelta(hours=1))
    assert _list(client, erp_ref="NO-STAMP").status_code == 200
    db = _S()
    try:
        assert db.get(Session, sid).last_reconciled_at is None, (
            "GET /api/nfc/sessions marked a session reconciled — reads must stamp nothing")
    finally:
        db.close()
    _clear(pid)


# ═══ TC-D61-08 ═══════════════════════════════════════════════════════════════

def test_tc_d61_08_commented_out_routes_are_absent(client, auth_headers, pid):
    for method, path, hdrs in (
        ("GET", f"/api/nfc/tags/{CAB}", auth_headers),
        ("POST", "/api/nfc/tags", auth_headers),
        ("POST", "/api/nfc/tags/bulk", auth_headers),
        ("DELETE", f"/api/nfc/tags/{CAB}/Q1", auth_headers),
        ("GET", "/api/nfc/sessions/by-user/someone", _erp()),
    ):
        r = client.request(method, path, headers=hdrs, json={} if method == "POST" else None)
        assert r.status_code in (404, 405), f"{method} {path} is still served: {r.status_code}"


# ═══ Step c — the ERP acknowledges what it BILLED ════════════════════════════
#
#  TC-D61-09  every id lands in exactly one bucket: acked / unknown / not_final / not_attributed
#  TC-D61-10  idempotent: a second ack keeps the FIRST timestamp
#  TC-D61-11  the request is bounded: no ids, or more than 500, is a 422
#  TC-D61-12  THE DEFECT: a session read while it was running stays in the backlog until acked
#  TC-D61-13  the detector moves on an ack, not on a read

def _ack(client, ids):
    return client.post("/api/nfc/sessions/ack", headers=_erp(), json={"session_ids": ids})


def _acked_at(sid):
    from app.models.session import Session
    db = _S()
    try:
        return db.get(Session, sid).erp_acked_at
    finally:
        db.close()


def test_tc_d61_09_every_id_lands_in_exactly_one_bucket(client, pid):
    _clear(pid)
    done = _seed(pid, "ACK-A", ended_at=datetime.utcnow() - timedelta(hours=1))
    running = _seed(pid, "ACK-A", socket_id=2)
    nobody = _seed(pid, None, ended_at=datetime.utcnow() - timedelta(hours=1), socket_id=3)

    body = _ack(client, [done, running, nobody, 99999999, done]).json()
    assert [a["session_id"] for a in body["acked"]] == [done], body
    assert body["not_final"] == [running]
    assert body["not_attributed"] == [nobody], (
        "a real session with no erp_ref must not be reported as unknown — that claims it "
        "does not exist")
    assert body["unknown"] == [99999999]
    assert _acked_at(done) is not None
    assert _acked_at(running) is None and _acked_at(nobody) is None
    _clear(pid)


def test_tc_d61_10_a_second_ack_keeps_the_first_timestamp(client, pid):
    _clear(pid)
    sid = _seed(pid, "ACK-TWICE", ended_at=datetime.utcnow() - timedelta(hours=1))
    first = _ack(client, [sid]).json()["acked"][0]["erp_acked_at"]
    stamped = _acked_at(sid)
    second = _ack(client, [sid]).json()["acked"][0]["erp_acked_at"]
    assert second == first and _acked_at(sid) == stamped, (
        "a repeated ack moved the timestamp that says when billing happened")
    _clear(pid)


def test_tc_d61_11_the_request_is_bounded(client, pid):
    assert _ack(client, []).status_code == 422
    assert _ack(client, list(range(1, 502))).status_code == 422
    assert _ack(client, list(range(1, 501))).status_code == 200
    r = client.post("/api/nfc/sessions/ack", json={"session_ids": [1]})
    assert r.status_code == 401, "the ack endpoint must require the ERP key"


def test_tc_d61_12_a_session_read_mid_charge_stays_in_the_backlog(client, pid):
    """The defect step c exists for. Before it, the ERP reading a session WHILE IT RAN stamped
    it reconciled, so when it ended unbilled it never appeared in the backlog."""
    from app.models.session import Session
    from app.services import erp_reconciliation
    _clear(pid)
    sid = _seed(pid, "ACK-MIDCHARGE", started_at=datetime.utcnow() - timedelta(days=20))
    assert client.get(f"/api/nfc/session/{sid}", headers=_erp()).status_code == 200  # mid-charge

    db = _S()
    try:
        s = db.get(Session, sid)
        s.status, s.ended_at = "completed", datetime.utcnow() - timedelta(days=19)
        db.commit()
    finally:
        db.close()

    db = _S()
    try:
        rows = erp_reconciliation.divergent_sessions(db)
    finally:
        db.close()
    assert sid in [r["session_id"] for r in rows], (
        "a session read while running and never acknowledged left the backlog")
    _clear(pid)


def test_tc_d61_13_the_detector_moves_on_an_ack_not_a_read(client, pid):
    from app.services import erp_reconciliation

    def state():
        db = _S()
        try:
            return next(r for r in erp_reconciliation.status_by_pedestal(db)
                        if r.pedestal_id == pid).state
        finally:
            db.close()

    _clear(pid)
    sid = _seed(pid, "ACK-DETECT", ended_at=datetime.utcnow() - timedelta(days=30),
                started_at=datetime.utcnow() - timedelta(days=31))
    assert state() == erp_reconciliation.STATE_SILENT_WITH_BACKLOG

    client.get(f"/api/nfc/session/{sid}", headers=_erp())
    client.get("/api/nfc/sessions", headers=_erp(), params={"erp_ref": "ACK-DETECT"})
    assert state() == erp_reconciliation.STATE_SILENT_WITH_BACKLOG, "a READ silenced the detector"

    _ack(client, [sid])
    assert state() == erp_reconciliation.STATE_IDLE, "an ack did not clear the backlog"
    _clear(pid)
