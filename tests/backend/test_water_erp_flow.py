"""Water in ERP mode (MODE 1) — the flow D6.1 decided, end to end (2026-10-12).

    ERP: POST /api/nfc/scan (valve)      -> a 5-minute pending reservation
    ERP: POST .../water/{V}/cmd activate -> REFUSED without a live reservation;
                                            otherwise the reservation is marked "activated"
                                            (a valve has no plug-in event to do it)
    Opta: OutletActivated (WATER)        -> the session takes the reservation's user
    ERP:  webhook                        -> the attributed water session reaches the ERP

What this file exists to close: water sessions never carried a user. Both the reservation
pickup and the user attachment sat under `if not is_water:`, and erp_webhook.is_erp_reportable
withholds an unattributed session — so in the real flow no water session ever reached the ERP.
TC-SIX-05 ("scanning a valve tag opens a water session") only checked /scan's reply text, and
TC-SIX-16 wrote nfc_user_id straight into the database, so nothing exercised the path.

  TC-WF-01  stop on V1 completes V1's water session — and nothing else
  TC-WF-02  activate with NO reservation is refused in ERP mode, nothing published
  TC-WF-03  activate with an EXPIRED reservation is refused
  TC-WF-04  activate with a live reservation publishes and marks it "activated"
  TC-WF-05  the whole flow: reservation -> activate -> OutletActivated -> user + webhook
  TC-WF-06  MODE 2 is unchanged — SKIPPED since D6.1 commented MODE 2 out
  TC-WF-07  OutletActivated on a valve with no reservation attaches nobody, reports nothing
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from conftest import TestSession as _S

CAB = "MAR_WATER_FLOW_01"


@pytest.fixture(scope="module")
def wpid(client, auth_headers):
    """A smart-mode pedestal with its own cabinet id, so pedestal 1 is left alone."""
    r = client.post("/api/pedestals/", json={
        "name": "Water Flow Pedestal", "location": "Dock W", "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.smart_mode = True
        db.commit()
    finally:
        db.close()
    return pid


def _clear(pid):
    from app.models.nfc_pending_session import NfcPendingSession
    from app.models.session import Session
    db = _S()
    try:
        db.query(NfcPendingSession).filter(NfcPendingSession.cabinet_id == CAB).delete()
        db.query(Session).filter(Session.pedestal_id == pid).delete()
        db.commit()
    finally:
        db.close()


def _seed_session(pid, socket_id, kind, status="active"):
    from app.models.session import Session
    db = _S()
    try:
        s = Session(pedestal_id=pid, socket_id=socket_id, type=kind, status=status,
                    started_at=datetime.utcnow())
        db.add(s)
        db.commit()
        return s.id
    finally:
        db.close()


def _session(sid):
    from app.models.session import Session
    db = _S()
    try:
        s = db.get(Session, sid)
        return None if s is None else {"status": s.status, "type": s.type,
                                       "erp_ref": s.erp_ref}
    finally:
        db.close()


def _water_cmd(client, auth_headers, pid, valve, action):
    published = []
    with patch("app.routers.controls.mqtt_service.publish",
               side_effect=lambda t, p, *a, **k: published.append((t, json.loads(p)))):
        r = client.post(f"/api/controls/pedestal/{pid}/water/{valve}/cmd",
                        json={"action": action}, headers=auth_headers)
    return r, published


# ═══ TC-WF-01 ════════════════════════════════════════════════════════════════

def test_tc_wf_01_stop_completes_the_valves_water_session_and_nothing_else(
        client, auth_headers, wpid):
    """The stop path looked the session up with socket_id=None, which SQL reads as
    `socket_id IS NULL` — matching no water session (they carry the valve number). The DB
    session then stayed active until the firmware's SessionEnded happened to close it.
    """
    _clear(wpid)
    water = _seed_session(wpid, 1, "water")
    power = _seed_session(wpid, 2, "electricity")

    r, published = _water_cmd(client, auth_headers, wpid, "V1", "stop")
    assert r.status_code == 200, r.text
    assert any(t == "opta/cmd/water/V1" for t, _ in published)

    assert _session(water)["status"] == "completed", (
        "stop on V1 left V1's water session active — the lookup did not find it")
    assert _session(power)["status"] == "active", (
        "stop on V1 completed an ELECTRICITY session on Q2")
    _clear(wpid)


def _add_reservation(valve, user_id, age_min=0, ttl_min=5, status="pending"):
    from app.models.nfc_pending_session import NfcPendingSession
    db = _S()
    try:
        now = datetime.utcnow() - timedelta(minutes=age_min)
        rec = NfcPendingSession(nfc_tag_id=f"WF-{valve}-{user_id}", user_id=user_id,
                                cabinet_id=CAB, socket_id=valve, created_at=now,
                                expires_at=now + timedelta(minutes=ttl_min), status=status)
        db.add(rec)
        db.commit()
        return rec.id
    finally:
        db.close()


def _reservation_status(rid):
    from app.models.nfc_pending_session import NfcPendingSession
    db = _S()
    try:
        return db.get(NfcPendingSession, rid).status
    finally:
        db.close()


def _webhook_configured():
    """Set the webhook URL on the settings object erp_webhook ACTUALLY reads.

    Not `app.config.settings`: test_startup_guards reloads app.config, which makes a new
    settings object, while erp_webhook keeps the one it imported. Setting the URL on the new
    object passed when this file ran alone and silently did nothing in the full suite.
    """
    from app.services import erp_webhook
    return patch.object(erp_webhook.settings, "erp_webhook_url", "https://erp.example/webhook")


def _outlet_activated(pid, valve):
    """Drive the firmware's OutletActivated for a valve; return the webhook mock."""
    from app.services.mqtt_handlers import _handle_event_outlet_activated
    with (
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
        patch("app.services.erp_webhook.post_erp_event", AsyncMock()) as post,
    ):
        db = _S()
        try:
            asyncio.run(_handle_event_outlet_activated(db, pid, valve, "WATER", {}))
        finally:
            db.close()
    return post


def _active_water(pid, valve_id):
    from app.models.session import Session
    db = _S()
    try:
        s = (db.query(Session).filter(Session.pedestal_id == pid, Session.socket_id == valve_id,
                                      Session.type == "water", Session.status == "active")
             .first())
        return None if s is None else {"id": s.id, "erp_ref": s.erp_ref}
    finally:
        db.close()


# ═══ TC-WF-02 / 03 ═══════════════════════════════════════════════════════════

def test_tc_wf_02_activate_without_a_reservation_is_refused(client, auth_headers, wpid):
    _clear(wpid)
    r, published = _water_cmd(client, auth_headers, wpid, "V1", "activate")
    assert r.status_code == 409, r.text
    assert "reservation" in r.json()["detail"].lower()
    assert published == [], f"the valve was told to open with no scan: {published}"


def test_tc_wf_03_an_expired_reservation_does_not_open_water(client, auth_headers, wpid):
    _clear(wpid)
    rid = _add_reservation("V1", "erp-late", age_min=6, ttl_min=5)
    r, published = _water_cmd(client, auth_headers, wpid, "V1", "activate")
    assert r.status_code == 409, r.text
    assert published == []
    assert _reservation_status(rid) != "activated"
    _clear(wpid)


def test_tc_wf_03b_a_reservation_for_the_other_valve_does_not_open_this_one(
        client, auth_headers, wpid):
    _clear(wpid)
    _add_reservation("V2", "erp-other")
    r, published = _water_cmd(client, auth_headers, wpid, "V1", "activate")
    assert r.status_code == 409, r.text
    assert published == []
    _clear(wpid)


# ═══ TC-WF-04 ════════════════════════════════════════════════════════════════

def test_tc_wf_04_activate_with_a_live_reservation_opens_and_consumes_it(
        client, auth_headers, wpid):
    _clear(wpid)
    rid = _add_reservation("V1", "erp-ok")
    r, published = _water_cmd(client, auth_headers, wpid, "V1", "activate")
    assert r.status_code == 200, r.text
    assert [(t, p["action"]) for t, p in published] == [("opta/cmd/water/V1", "activate")]
    assert _reservation_status(rid) == "activated", (
        "the reservation was not consumed, so OutletActivated has nothing to attach")
    _clear(wpid)


# ═══ TC-WF-05 ════════════════════════════════════════════════════════════════

def test_tc_wf_05_the_whole_flow_gives_the_water_session_its_user_and_reaches_the_erp(
        client, auth_headers, wpid):
    """The path TC-SIX-05's name promised and nothing exercised."""
    _clear(wpid)
    _add_reservation("V2", "erp-water-customer")
    r, _ = _water_cmd(client, auth_headers, wpid, "V2", "activate")
    assert r.status_code == 200, r.text

    with _webhook_configured():
        post = _outlet_activated(wpid, "V2")

    s = _active_water(wpid, 2)
    assert s is not None, "OutletActivated did not open a water session"
    assert s["erp_ref"] == "erp-water-customer", (
        f"the water session carries erp_ref {s['erp_ref']!r} — unattributed water is "
        f"withheld from the ERP and can never be billed")
    # call_count, not await_count: the webhook goes out via asyncio.create_task, and
    # asyncio.run may cancel that task before it is awaited (it passed alone and failed in
    # the full suite). What is asserted is the cabinet's DECISION to report — the call.
    assert post.call_count == 1, "the attributed water session was not reported to the ERP"
    payload = post.call_args.args[0]
    assert payload["session_type"] == "water" and payload["socket_id"] == "V2"
    assert payload["erp_ref"] == "erp-water-customer"
    _clear(wpid)


# ═══ TC-WF-06 / 07 ═══════════════════════════════════════════════════════════

@pytest.mark.skip(reason="D6.1 (2026-10-12): MODE 2 is commented out — a water activate "
                         "always needs a reservation now (TC-WF-02)")
def test_tc_wf_06_mode_2_needs_no_reservation(client, auth_headers, wpid):
    from app.config import settings
    _clear(wpid)
    with patch.object(settings, "nfc_direct_client_mode", True):
        r, published = _water_cmd(client, auth_headers, wpid, "V1", "activate")
    assert r.status_code == 200, r.text
    assert any(t == "opta/cmd/water/V1" for t, _ in published)
    _clear(wpid)


def test_tc_wf_07_a_valve_opened_without_a_scan_attaches_nobody_and_reports_nothing(wpid):
    """E.g. an OutletActivated the firmware sends on its own. No reservation -> no user ->
    nothing to the ERP. Not a new rule — is_erp_reportable — but water now reaches it."""
    _clear(wpid)
    with _webhook_configured():
        post = _outlet_activated(wpid, "V1")
    s = _active_water(wpid, 1)
    assert s is not None and s["erp_ref"] is None
    assert post.call_count == 0
    _clear(wpid)
