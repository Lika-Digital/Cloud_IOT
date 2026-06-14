"""v3.21 — Backend bug-fix bundle B1 / B2 / B3 / B4.

Reuses the proven harness from test_meter_load.py (in-memory file DB, `_simulate`,
`_ensure_cabinet`, `_seed_hw_config`, `_get_socket_cfg`, `_TestSession`, CABINET)
plus the conftest `client` / `auth_headers` fixtures for REST assertions.

  B1 — tolerant hwconfig parser (recover sockets from a 502-byte-truncated payload)
  B2 — fault precedence display (fault > active > pending > idle)
  B3 — honest diagnostic (no synthesized OK from a stale connection flag)
  B4 — power value sanity clamp (display/audit only; overload+billing untouched)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from unittest.mock import patch, AsyncMock

import pytest

from test_meter_load import (
    _simulate, _ensure_cabinet, _seed_hw_config, _get_socket_cfg,
    _TestSession, CABINET,
)


# ── B1 helpers ───────────────────────────────────────────────────────────────

def _simulate_raw_hwconfig(raw: str) -> list[dict]:
    """Inject a RAW (possibly truncated) opta/config/hardware string directly,
    bypassing json.dumps so the truncation survives into the handler."""
    broadcasts: list[dict] = []

    async def capture(msg):
        broadcasts.append(msg)

    from app.services.mqtt_handlers import _handle_opta_hardware_config
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=capture),
    ):
        asyncio.run(_handle_opta_hardware_config(raw))
    return broadcasts


def _truncated_hwconfig(cabinet: str) -> str:
    """Realistic firmware-2.5.0 truncation: complete `sockets`, severed `valves`."""
    return (
        '{"cabinetId":"' + cabinet + '","firmwareVersion":"2.5.0","sockets":['
        '{"socketId":"Q1","meterType":"ABB D13 15-M 65","phases":3,"ratedAmps":65,"modbusAddress":1},'
        '{"socketId":"Q2","meterType":"ABB D11 15-M 40","phases":1,"ratedAmps":40,"modbusAddress":2},'
        '{"socketId":"Q3","meterType":"ABB D11 15-M 40","phases":1,"ratedAmps":40,"modbusAddress":3},'
        '{"socketId":"Q4","meterType":"ABB D11 15-M 40","phases":1,"ratedAmps":40,"modbusAddress":4}],'
        '"valves":[{"valveId":"V1","ratedLitersPerMin":20},{"valveId":"V2","ratedLit'
    )


# ── B1 — tolerant hwconfig parser ───────────────────────────────────────────

def test_b1_complete_json_stores_sockets_and_broadcasts_valves():
    pid = _ensure_cabinet()
    broadcasts = _simulate("opta/config/hardware", {
        "cabinetId": CABINET,
        "firmwareVersion": "2.5.0",
        "sockets": [{"socketId": "Q1", "meterType": "ABB D13 15-M 65",
                     "phases": 3, "ratedAmps": 65, "modbusAddress": 1}],
        "valves": [{"valveId": "V1", "ratedLitersPerMin": 20},
                   {"valveId": "V2", "ratedLitersPerMin": 20}],
    })
    assert _get_socket_cfg(pid, 1).rated_amps == pytest.approx(65.0)
    ev = [b for b in broadcasts if b.get("event") == "hardware_config_updated"][0]
    assert len(ev["data"]["valves"]) == 2  # valves present when JSON is complete


def test_b1_truncated_payload_recovers_all_four_sockets():
    pid = _ensure_cabinet()
    _simulate_raw_hwconfig(_truncated_hwconfig(CABINET))
    for sid, rated in ((1, 65.0), (2, 40.0), (3, 40.0), (4, 40.0)):
        cfg = _get_socket_cfg(pid, sid)
        assert cfg is not None, f"socket {sid} not stored from truncated payload"
        assert cfg.rated_amps == pytest.approx(rated)
        assert cfg.meter_type


def test_b1_truncated_payload_logs_warning(caplog):
    _ensure_cabinet()
    with caplog.at_level("WARNING"):
        _simulate_raw_hwconfig(_truncated_hwconfig(CABINET))
    assert any("Truncated payload recovered" in r.message for r in caplog.records)


def test_b1_truncated_payload_logs_bytes_dropped(caplog):
    _ensure_cabinet()
    with caplog.at_level("WARNING"):
        _simulate_raw_hwconfig(_truncated_hwconfig(CABINET))
    assert any("dropped" in r.message.lower() for r in caplog.records)


def test_b1_truncated_partial_parse_sets_hw_config_received_at():
    pid = _ensure_cabinet()
    _simulate_raw_hwconfig(_truncated_hwconfig(CABINET))
    assert _get_socket_cfg(pid, 2).hw_config_received_at is not None


def test_b1_unrecoverable_when_sockets_array_itself_truncated():
    pid = _ensure_cabinet()
    raw = ('{"cabinetId":"' + CABINET + '","firmwareVersion":"2.5.0","sockets":['
           '{"socketId":"Q9","meterType":"ABB D13')
    _simulate_raw_hwconfig(raw)
    assert _get_socket_cfg(pid, 9) is None  # nothing stored


def test_b1_awaiting_config_clears_after_partial_parse():
    pid = _ensure_cabinet()
    db = _TestSession()
    try:
        from app.models.socket_config import SocketConfig
        cfg = db.query(SocketConfig).filter_by(pedestal_id=pid, socket_id=3).first()
        if cfg:
            cfg.rated_amps = None
            db.commit()
    finally:
        db.close()
    _simulate_raw_hwconfig(_truncated_hwconfig(CABINET))
    # rated_amps populated = the field that drives "awaiting hardware configuration".
    assert _get_socket_cfg(pid, 3).rated_amps == pytest.approx(40.0)


# ── B2 — fault precedence display ────────────────────────────────────────────

def _seed_socket_state(pedestal_id: int, socket_id: int, connected: bool):
    from app.models.pedestal_config import SocketState
    db = _TestSession()
    try:
        ss = db.query(SocketState).filter_by(pedestal_id=pedestal_id, socket_id=socket_id).first()
        if ss is None:
            ss = SocketState(pedestal_id=pedestal_id, socket_id=socket_id, connected=connected)
            db.add(ss)
        else:
            ss.connected = connected
        ss.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _seed_active_session(pedestal_id: int, socket_id: int) -> int:
    from app.services.session_service import session_service
    db = _TestSession()
    try:
        s = session_service.create_pending(db, pedestal_id, socket_id, "electricity")
        session_service.activate(db, s)
        return s.id
    finally:
        db.close()


def test_b2_hw_fault_displays_fault_even_with_active_session():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, rated_amps=16.0, breaker_state="closed")
    _seed_socket_state(pid, 1, connected=True)
    _seed_active_session(pid, 1)
    from app.services.mqtt_handlers import _compute_socket_display_state
    db = _TestSession()
    try:
        state = _compute_socket_display_state(db, pid, 1, raw_state="active", hw_status="fault")
    finally:
        db.close()
    assert state == "fault"


def test_b2_breaker_tripped_displays_fault_even_with_active_session():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, rated_amps=16.0, breaker_state="tripped")
    _seed_socket_state(pid, 1, connected=True)
    _seed_active_session(pid, 1)
    from app.services.mqtt_handlers import _compute_socket_display_state
    db = _TestSession()
    try:
        state = _compute_socket_display_state(db, pid, 1)  # no live msg → uses persisted
    finally:
        db.close()
    assert state == "fault"


def test_b2_hw_ok_active_session_displays_active():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, rated_amps=16.0, breaker_state="closed")
    _seed_socket_state(pid, 1, connected=True)
    _seed_active_session(pid, 1)
    from app.services.mqtt_handlers import _compute_socket_display_state
    db = _TestSession()
    try:
        state = _compute_socket_display_state(db, pid, 1, raw_state="active", hw_status="ok")
    finally:
        db.close()
    assert state == "active"


def test_b2_fault_precedence_in_websocket_broadcast():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, rated_amps=16.0, breaker_state="closed")
    _seed_active_session(pid, 1)
    broadcasts: list[dict] = []

    async def capture(msg):
        broadcasts.append(msg)

    from app.services.mqtt_handlers import handle_message
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=capture),
        patch("app.services.mqtt_handlers.ws_manager.broadcast_to_session", new=AsyncMock()),
    ):
        asyncio.run(handle_message(
            "opta/sockets/Q1/status",
            json.dumps({"cabinetId": CABINET, "id": "Q1", "state": "fault", "hw_status": "fault"}),
        ))
    scs = [b for b in broadcasts if b.get("event") == "socket_state_changed"]
    assert scs, "no socket_state_changed broadcast emitted"
    assert scs[-1]["data"]["state"] == "fault"


def test_b2_fault_precedence_in_rest_response(client, auth_headers):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, rated_amps=16.0, breaker_state="tripped")
    _seed_socket_state(pid, 1, connected=True)
    r = client.get(f"/api/pedestals/{pid}/sockets/1/load", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["display_state"] == "fault"


def test_b2_internal_session_state_not_modified_by_precedence():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, rated_amps=16.0, breaker_state="tripped")
    sid_session = _seed_active_session(pid, 1)
    from app.services.mqtt_handlers import _compute_socket_display_state
    from app.models.session import Session as _S
    db = _TestSession()
    try:
        _compute_socket_display_state(db, pid, 1, raw_state="fault", hw_status="fault")
        sess = db.get(_S, sid_session)
        assert sess.status == "active"  # display-only; session untouched
    finally:
        db.close()


# ── B3 — honest diagnostic ───────────────────────────────────────────────────

def _set_opta_connected(pedestal_id: int, connected: bool):
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(pedestal_id=pedestal_id).first()
        cfg.opta_connected = 1 if connected else 0
        db.commit()
    finally:
        db.close()


def test_b3_timeout_returns_unknown_not_synthesized_ok(client, auth_headers):
    pid = _ensure_cabinet()
    _set_opta_connected(pid, True)  # stale connected flag must NOT yield all_ok
    with (
        patch("app.routers.diagnostics.mqtt_service.publish"),
        patch("app.routers.diagnostics._await_diag_event",
              new=AsyncMock(side_effect=asyncio.TimeoutError)),
    ):
        r = client.post(f"/api/pedestals/{pid}/diagnostics/run", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["all_ok"] is False
    assert body["status"] == "unknown"
    assert "No diagnostic response received from device" in (body.get("error") or "")


def test_b3_fresh_response_returns_real_device_data(client, auth_headers):
    pid = _ensure_cabinet()
    from app.services.diagnostics_manager import diagnostics_manager, EXPECTED_SENSORS

    async def _seed_and_return(*_a, **_k):
        diagnostics_manager._results[pid] = {s: "ok" for s in EXPECTED_SENSORS}
        return None

    with (
        patch("app.routers.diagnostics.mqtt_service.publish"),
        patch("app.routers.diagnostics._await_diag_event",
              new=AsyncMock(side_effect=_seed_and_return)),
    ):
        r = client.post(f"/api/pedestals/{pid}/diagnostics/run", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["all_ok"] is True


def test_b3_fresh_fault_response_reports_fault(client, auth_headers):
    pid = _ensure_cabinet()
    from app.services.diagnostics_manager import diagnostics_manager, EXPECTED_SENSORS

    async def _seed_and_return(*_a, **_k):
        sensors = {s: "ok" for s in EXPECTED_SENSORS}
        sensors["socket_1"] = "fail"
        diagnostics_manager._results[pid] = sensors
        return None

    with (
        patch("app.routers.diagnostics.mqtt_service.publish"),
        patch("app.routers.diagnostics._await_diag_event",
              new=AsyncMock(side_effect=_seed_and_return)),
    ):
        r = client.post(f"/api/pedestals/{pid}/diagnostics/run", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "fault"
    assert body["all_ok"] is False


# ── B4 — power value sanity clamp ────────────────────────────────────────────

def test_b4_clamp_fires_and_logs_when_reported_exceeds_50x(caplog):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 2, rated_amps=40.0, phases=1)
    with caplog.at_level("WARNING"):
        _simulate("opta/meters/Q2/telemetry", {
            "cabinetId": CABINET, "socketId": "Q2",
            "currentAmps": 26.0, "voltageV": 227.5, "powerKw": 395.974,
            "powerFactor": 0.667, "energyKwh": 0.0, "frequency": 50.0,
        })
    cfg = _get_socket_cfg(pid, 2)
    assert cfg.meter_power_kw_raw == pytest.approx(395.974)            # raw preserved
    assert cfg.meter_power_kw == pytest.approx(227.5 * 26.0 * 0.001)   # computed (no PF, 1-ph)
    assert any("sanity clamp fired" in r.message for r in caplog.records)


def test_b4_raw_stored_alongside_clamped():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 2, rated_amps=40.0, phases=1)
    _simulate("opta/meters/Q2/telemetry", {
        "cabinetId": CABINET, "socketId": "Q2",
        "currentAmps": 26.0, "voltageV": 227.5, "powerKw": 395.974, "powerFactor": 0.667,
    })
    cfg = _get_socket_cfg(pid, 2)
    assert cfg.meter_power_kw_raw == pytest.approx(395.974)
    assert cfg.meter_power_kw != cfg.meter_power_kw_raw


def test_b4_no_clamp_when_voltage_zero():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 3, rated_amps=40.0, phases=1)
    _simulate("opta/meters/Q3/telemetry", {
        "cabinetId": CABINET, "socketId": "Q3",
        "currentAmps": 0.0, "voltageV": 0.0, "powerKw": 999.0, "powerFactor": 0.0,
    })
    cfg = _get_socket_cfg(pid, 3)
    assert cfg.meter_power_kw == pytest.approx(999.0)       # reported used as-is
    assert cfg.meter_power_kw_raw == pytest.approx(999.0)


def test_b4_no_clamp_when_within_50x():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 2, rated_amps=40.0, phases=1)
    _simulate("opta/meters/Q2/telemetry", {
        "cabinetId": CABINET, "socketId": "Q2",
        "currentAmps": 26.0, "voltageV": 227.5, "powerKw": 3.0, "powerFactor": 0.667,
    })
    cfg = _get_socket_cfg(pid, 2)
    assert cfg.meter_power_kw == pytest.approx(3.0)         # within 50x → unchanged
    assert cfg.meter_power_kw_raw == pytest.approx(3.0)


def test_b4_three_phase_clamp_uses_pf(caplog):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, rated_amps=65.0, phases=3)
    with caplog.at_level("WARNING"):
        _simulate("opta/meters/Q1/telemetry", {
            "cabinetId": CABINET, "socketId": "Q1",
            "currentAmpsL1": 26.0, "currentAmpsL2": 26.0, "currentAmpsL3": 26.0,
            "currentAmpsTotal": 26.0,
            "voltageL1": 230.0, "voltageL2": 230.0, "voltageL3": 230.0,
            "powerKwTotal": 600.0, "powerFactor": 0.9, "frequency": 50.0,
        })
    cfg = _get_socket_cfg(pid, 1)
    assert cfg.meter_power_kw_raw == pytest.approx(600.0)
    # computed = avg_v(230) * I_total(26) * PF(0.9) * 0.001
    assert cfg.meter_power_kw == pytest.approx(230.0 * 26.0 * 0.9 * 0.001)


def test_b4_rest_response_exposes_power_kw_raw(client, auth_headers):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 2, rated_amps=40.0, phases=1)
    _simulate("opta/meters/Q2/telemetry", {
        "cabinetId": CABINET, "socketId": "Q2",
        "currentAmps": 26.0, "voltageV": 227.5, "powerKw": 395.974, "powerFactor": 0.667,
    })
    r = client.get(f"/api/pedestals/{pid}/sockets/2/load", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "power_kw_raw" in body
    assert body["power_kw_raw"] == pytest.approx(395.974)
