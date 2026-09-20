"""
Socket state consistency across the Dashboard views (v3.39)
============================================================

Guards the bug where the fleet overview and the pedestal detail screen
disagreed about the same socket: the fleet card showed "3 Active" (counted from
`sessions.status == 'active'`) while every socket badge on the detail screen
showed IDLE — next to a live meter reading of 1.9 A.

Three independent defects produced that, each covered here:

  1. `_handle_opta_meter_telemetry` never emitted `socket_state_changed`, so the
     meter-driven active transition (Smart Mode OFF / standalone draw) never
     reached any dashboard.                      → TC-SSC-01..03
  2. `_socket_delivering_power` ignored `meter_load_updated_at`, so the last
     reading of a cabinet that went offline counted as live draw forever — a
     socket frozen "active" and a standalone usage session that never closed.
                                                 → TC-SSC-04..06
  3. Nothing finalised sessions left `active` on a silent cabinet (the pending
     watchdog only touches `pending`, idle auto-finalise only customer/NFC
     sessions, the standalone grace close only `origin='standalone'`).
                                                 → TC-SSC-07..08

  TC-SSC-09..10 assert the end-to-end invariant the operator actually sees, over
  REST: every session the fleet counter counts resolves to an `active` socket.
  TC-SSC-11 is a cross-layer guard — the backend ships `display_state` on every
  load read, and the frontend must still consume it. Dropping it on the client
  is what made the badge fall back to IDLE on every page load, and it is
  invisible to any backend-only test.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from test_meter_load import (
    _simulate, _ensure_cabinet, _seed_hw_config, _get_socket_cfg,
    _TestSession, CABINET,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SOCKET = 1


@pytest.fixture(autouse=True)
def _reset_socket_state():
    """Every test starts from a clean socket: no sessions, no operator marker,
    no remembered broadcast state, breaker closed."""
    from app.models.pedestal_config import PedestalConfig, SocketState
    from app.models.session import Session as SModel
    from app.services import mqtt_handlers as mh

    mh._meter_last_display_state.clear()
    mh._standalone_usage_last.clear()
    mh._standalone_usage_low_since.clear()
    mh._meter_energy_last.clear()
    mh._customer_idle_since.clear()

    pid = _ensure_cabinet()
    db = _TestSession()
    try:
        db.query(SModel).filter(SModel.pedestal_id == pid).delete(synchronize_session=False)
        ss = db.query(SocketState).filter_by(pedestal_id=pid, socket_id=SOCKET).first()
        if ss is not None:
            ss.operator_status = None
            ss.operator_status_at = None
            ss.connected = True
        cfg = db.query(PedestalConfig).filter_by(pedestal_id=pid).first()
        if cfg is not None:
            cfg.smart_mode = True
        db.commit()
    finally:
        db.close()
    _seed_hw_config(pid, SOCKET, meter_type="ABB D11 15-M 40", phases=1,
                    rated_amps=32.0, breaker_state="closed",
                    meter_power_kw=0.0, meter_current_amps=0.0)
    yield


# ── helpers ──────────────────────────────────────────────────────────────────

def _telemetry(amps: float, kw: float) -> list[dict]:
    return _simulate(f"opta/meters/Q{SOCKET}/telemetry", {
        "cabinetId": CABINET, "socketId": f"Q{SOCKET}",
        "currentAmps": amps, "voltageV": 230.0, "powerKw": kw,
        "powerFactor": 0.95, "energyKwh": 0.0, "frequency": 50.0,
    })


def _state_events(broadcasts: list[dict]) -> list[dict]:
    return [b for b in broadcasts if b.get("event") == "socket_state_changed"]


def _display_state(pid: int, socket_id: int = SOCKET) -> str:
    from app.services.mqtt_handlers import _compute_socket_display_state
    db = _TestSession()
    try:
        return _compute_socket_display_state(db, pid, socket_id)
    finally:
        db.close()


def _set_meter(pid: int, *, amps: float, kw: float, age_s: float) -> None:
    """Write a meter reading stamped `age_s` seconds in the past."""
    _seed_hw_config(
        pid, SOCKET,
        meter_current_amps=amps, meter_power_kw=kw,
        meter_load_updated_at=datetime.utcnow() - timedelta(seconds=age_s),
    )


def _seed_active_session(pid: int, socket_id: int = SOCKET, **fields) -> int:
    from app.models.session import Session as SModel
    db = _TestSession()
    try:
        s = SModel(pedestal_id=pid, socket_id=socket_id, type="electricity",
                   status="active", started_at=datetime.utcnow(),
                   energy_kwh=0.0, **fields)
        db.add(s)
        db.commit()
        return s.id
    finally:
        db.close()


def _session_row(session_id: int):
    from app.models.session import Session as SModel
    db = _TestSession()
    try:
        return db.get(SModel, session_id)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
# TC-SSC-01..03 — meter telemetry drives the socket_state_changed broadcast
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ssc_01_telemetry_broadcasts_active_on_live_draw():
    """A socket that starts drawing power must announce it. Before v3.39 this
    handler emitted load alarms only, so the badge never left IDLE."""
    pid = _ensure_cabinet()
    events = _state_events(_telemetry(amps=8.3, kw=1.9))
    assert len(events) == 1, f"expected one socket_state_changed, got {events}"
    assert events[0]["data"]["socket_id"] == SOCKET
    assert events[0]["data"]["state"] == "active"
    assert _display_state(pid) == "active"


def test_tc_ssc_02_telemetry_does_not_rebroadcast_unchanged_state():
    """Telemetry lands every ~5 s; the event must stay change-only."""
    _ensure_cabinet()
    assert len(_state_events(_telemetry(amps=8.3, kw=1.9))) == 1
    assert _state_events(_telemetry(amps=8.4, kw=1.9)) == []
    assert _state_events(_telemetry(amps=8.2, kw=1.9)) == []


def test_tc_ssc_03_telemetry_broadcasts_idle_when_draw_stops():
    pid = _ensure_cabinet()
    _telemetry(amps=8.3, kw=1.9)
    events = _state_events(_telemetry(amps=0.0, kw=0.0))
    assert len(events) == 1
    assert events[0]["data"]["state"] == "idle"
    assert _display_state(pid) == "idle"


# ═══════════════════════════════════════════════════════════════════════════
# TC-SSC-04..06 — a stale reading is not live draw
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ssc_04_stale_reading_is_not_delivering_power():
    from app.services import mqtt_handlers as mh
    pid = _ensure_cabinet()

    _set_meter(pid, amps=8.3, kw=1.9, age_s=5)
    assert mh._socket_delivering_power(_get_socket_cfg(pid, SOCKET)) is True

    _set_meter(pid, amps=8.3, kw=1.9, age_s=mh._METER_STALE_AFTER_S + 30)
    assert mh._socket_delivering_power(_get_socket_cfg(pid, SOCKET)) is False


def test_tc_ssc_05_never_reported_meter_is_not_delivering_power():
    from app.services import mqtt_handlers as mh
    pid = _ensure_cabinet()
    _seed_hw_config(pid, SOCKET, meter_current_amps=8.3, meter_power_kw=1.9,
                    meter_load_updated_at=None)
    assert mh._socket_delivering_power(_get_socket_cfg(pid, SOCKET)) is False


def test_tc_ssc_06_stale_draw_falls_back_to_idle_not_frozen_active():
    """The reported symptom: a cabinet 460 h offline still showed 1.9 A and the
    socket must not be reported active off that frozen reading."""
    from app.services import mqtt_handlers as mh
    pid = _ensure_cabinet()
    _set_meter(pid, amps=8.3, kw=1.9, age_s=mh._METER_STALE_AFTER_S + 30)
    assert _display_state(pid) == "idle"


def test_tc_ssc_07_standalone_watchdog_ignores_stale_draw():
    """Smart Mode OFF + a stale reading must not open a usage session that then
    never closes (the draw never 'stops', so the grace close never fires)."""
    from app.models.pedestal_config import PedestalConfig
    from app.models.session import Session as SModel
    from app.services import mqtt_handlers as mh

    pid = _ensure_cabinet()
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(pedestal_id=pid).first()
        cfg.smart_mode = False
        db.commit()
    finally:
        db.close()
    _set_meter(pid, amps=8.3, kw=1.9, age_s=mh._METER_STALE_AFTER_S + 30)

    async def _noop(*a, **k):
        return None

    with patch.object(mh, "SessionLocal", _TestSession), \
         patch("app.services.mqtt_handlers.ws_manager.broadcast", new=_noop):
        asyncio.run(mh._standalone_usage_tick(datetime.utcnow()))

    db = _TestSession()
    try:
        opened = db.query(SModel).filter_by(
            pedestal_id=pid, socket_id=SOCKET, status="active").first()
    finally:
        db.close()
    assert opened is None, "stale meter reading opened a standalone session"


# ═══════════════════════════════════════════════════════════════════════════
# TC-SSC-08 — comm loss finalises sessions nothing else owns
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ssc_08_comm_loss_completes_orphan_active_session():
    """An operator-activated session (no customer, not standalone) was owned by
    no watchdog and stayed `active` forever once the Opta dropped off."""
    import app.main as main_mod

    pid = _ensure_cabinet()
    session_id = _seed_active_session(pid)
    broadcasts: list[dict] = []

    async def capture(msg):
        broadcasts.append(msg)

    with patch.object(main_mod, "SessionLocal", _TestSession), \
         patch("app.main.ws_manager.broadcast", side_effect=capture):
        asyncio.run(main_mod._close_sessions_on_comm_loss(pid))

    s = _session_row(session_id)
    assert s.status == "completed"
    assert s.end_reason == "comm_loss"
    assert s.ended_at is not None
    assert any(b.get("event") == "session_completed" for b in broadcasts)
    assert any(b.get("event") == "socket_state_changed"
               and b["data"]["state"] == "idle" for b in broadcasts)

    # Idempotent — a second pass on the now-clean pedestal does nothing.
    broadcasts.clear()
    with patch.object(main_mod, "SessionLocal", _TestSession), \
         patch("app.main.ws_manager.broadcast", side_effect=capture):
        asyncio.run(main_mod._close_sessions_on_comm_loss(pid))
    assert broadcasts == []


# ═══════════════════════════════════════════════════════════════════════════
# TC-SSC-09..10 — the operator-visible invariant, over REST
# ═══════════════════════════════════════════════════════════════════════════

def _fleet_active_sockets(client, headers, pid: int) -> set[int]:
    """What the fleet card counts: rows in sessions with status='active'."""
    r = client.get(f"/api/sessions/active?pedestal_id={pid}", headers=headers)
    assert r.status_code == 200, r.text
    return {
        s["socket_id"] for s in r.json()
        if s["type"] == "electricity" and s["socket_id"] is not None
    }


def _rest_display_state(client, headers, pid: int, socket_id: int) -> str:
    """What the pedestal detail badge renders, from the same payload the
    dashboard hydrates on mount."""
    r = client.get(f"/api/pedestals/{pid}/sockets/{socket_id}/load", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "display_state" in body, "load payload lost display_state"
    return body["display_state"]


def test_tc_ssc_09_every_counted_session_maps_to_an_active_socket(client, auth_headers):
    """THE invariant. The fleet counter and the socket badge read two different
    sources; every session the counter counts must resolve to a socket the
    detail screen shows as active (or fault, which outranks active by design).
    """
    pid = _ensure_cabinet()
    _telemetry(amps=8.3, kw=1.9)          # socket really is passing power
    _seed_active_session(pid)

    counted = _fleet_active_sockets(client, auth_headers, pid)
    assert counted == {SOCKET}
    for socket_id in counted:
        state = _rest_display_state(client, auth_headers, pid, socket_id)
        assert state in ("active", "fault"), (
            f"fleet counts socket {socket_id} as active but the detail view "
            f"renders {state!r} — the two dashboard views disagree"
        )


def test_tc_ssc_10_offline_cabinet_leaves_both_views_agreeing_on_idle(client, auth_headers):
    """Cabinet goes silent mid-session: the counter must drain and the badge
    must go idle — not 3-vs-0 between the two screens."""
    import app.main as main_mod
    from app.services import mqtt_handlers as mh

    pid = _ensure_cabinet()
    _telemetry(amps=8.3, kw=1.9)
    _seed_active_session(pid)
    assert _fleet_active_sockets(client, auth_headers, pid) == {SOCKET}

    # Cabinet stops reporting: the last reading ages out.
    _set_meter(pid, amps=8.3, kw=1.9, age_s=mh._METER_STALE_AFTER_S + 30)

    async def _noop(*a, **k):
        return None

    with patch.object(main_mod, "SessionLocal", _TestSession), \
         patch("app.main.ws_manager.broadcast", new=_noop):
        asyncio.run(main_mod._close_sessions_on_comm_loss(pid))

    assert _fleet_active_sockets(client, auth_headers, pid) == set()
    assert _rest_display_state(client, auth_headers, pid, SOCKET) == "idle"


# ═══════════════════════════════════════════════════════════════════════════
# TC-SSC-11 — cross-layer: the frontend must consume display_state
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ssc_11_frontend_consumes_display_state():
    """GAP BE<->FE. The backend returns `display_state` on every load read, but
    `socket_state_changed` is change-only — so if the client stops hydrating
    from REST, every badge silently falls back to IDLE on page load while the
    backend looks perfectly correct. Pin both halves of the contract.
    """
    api_ts = (REPO_ROOT / "frontend/src/api/meterLoad.ts").read_text(encoding="utf-8")
    assert "display_state" in api_ts, (
        "SocketLoadState no longer declares display_state — the REST payload's "
        "socket state is being dropped at the API layer"
    )

    panel = (REPO_ROOT / "frontend/src/components/pedestal/SocketLoadMeterPanel.tsx").read_text(encoding="utf-8")
    assert "display_state" in panel and "setSocketComputedState" in panel, (
        "SocketLoadMeterPanel no longer hydrates socketComputedStates from the "
        "load payload — socket badges will read IDLE until a WS state change"
    )
