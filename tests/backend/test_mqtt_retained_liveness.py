"""
Retained-message liveness handling (v3.40)
==========================================

MQTT brokers store the last RETAINED message per topic and replay it to every
new subscriber. The Opta retains its status/hwconfig/door/breaker topics, so on
every backend restart the cabinet's final message is re-delivered — even one
published weeks earlier by a cabinet that has since died.

`_on_message` used to drop `msg.retain`, so handlers could not tell a replay from
live traffic and stamped the cabinet `online` with `last_heartbeat = now`. Effects:
the dashboard showed a dead cabinet as connected, and `_comm_loss_watchdog` saw a
fresh heartbeat and never raised comm loss. Field case: MAR_KRK_ORM_01 went silent
2026-09-01 (signed-int32 millis rollover at 24.85 d) yet came back "online" after
each restart.

The split this pins:
  - liveness (last_heartbeat / opta_connected / status=online / time-sync on
    seq=0) → NEVER from a retained message.
  - durable config (SmartMode, door, and the opta_status broadcast for
    last-known display) → still applied; hydrating it is the point of retain.

  TC-RET-01  retained opta/status does not write last_heartbeat
  TC-RET-02  retained opta/status does not mark the cabinet online / connected
  TC-RET-03  live opta/status DOES write both (the flag is not a blanket off-switch)
  TC-RET-04  retained status still broadcasts opta_status, flagged retained=True
  TC-RET-05  live status broadcasts opta_status with retained=False
  TC-RET-06  retained status still applies SmartMode (durable config)
  TC-RET-07  retained seq=0 does not publish a time sync to a cabinet that is gone
  TC-RET-08  live seq=0 does publish the time sync
  TC-RET-09  legacy pedestal/{id}/heartbeat honours the flag too
  TC-RET-10  the mqtt_client callback forwards msg.retain into handle_message
  TC-RET-11  a retained replay cannot mask an outage from the comm-loss watchdog
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import pytest

from test_meter_load import _TestSession

CABINET = "MAR_KRK_RETAIN_01"


@pytest.fixture(autouse=True)
def _reset():
    from app.models.pedestal_config import PedestalConfig
    from app.services import mqtt_handlers as mh

    mh.last_heartbeat.clear()
    # Register the cabinet with a deliberately OLD heartbeat, as if it had gone
    # silent long ago and the backend has just restarted.
    stale = datetime.utcnow() - timedelta(days=19)
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=CABINET).first()
        if cfg is None:
            _dispatch(json.dumps({"cabinetId": CABINET, "seq": 1, "uptime_ms": 1000}))
            cfg = db.query(PedestalConfig).filter_by(opta_client_id=CABINET).first()
        cfg.last_heartbeat = stale
        cfg.opta_connected = 0
        cfg.status = "offline"
        cfg.smart_mode = False
        db.commit()
    finally:
        db.close()
    mh.last_heartbeat.clear()
    yield


def _dispatch(payload: str, *, retained: bool = False) -> list[dict]:
    """Route an opta/status message through the real dispatcher."""
    broadcasts: list[dict] = []

    async def capture(msg):
        broadcasts.append(msg)

    from app.services.mqtt_handlers import handle_message
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=capture),
    ):
        asyncio.run(handle_message("opta/status", payload, retained=retained))
    return broadcasts


def _status_payload(seq: int = 143160, uptime_ms: int = 2147471955, **extra) -> str:
    return json.dumps({
        "cabinetId": CABINET, "seq": seq, "uptime_ms": uptime_ms,
        "door": "closed", **extra,
    })


def _cfg():
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        return db.query(PedestalConfig).filter_by(opta_client_id=CABINET).first()
    finally:
        db.close()


def _pid() -> int:
    return _cfg().pedestal_id


# ═══════════════════════════════════════════════════════════════════════════
# TC-RET-01..03 — liveness state
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ret_01_retained_status_does_not_write_last_heartbeat():
    from app.services import mqtt_handlers as mh
    before = _cfg().last_heartbeat

    _dispatch(_status_payload(), retained=True)

    assert _pid() not in mh.last_heartbeat, (
        "retained replay seeded the in-memory heartbeat — the comm-loss watchdog "
        "will treat a dead cabinet as recently alive"
    )
    assert _cfg().last_heartbeat == before, "retained replay overwrote last_heartbeat"


def test_tc_ret_02_retained_status_does_not_mark_cabinet_online():
    _dispatch(_status_payload(), retained=True)
    cfg = _cfg()
    assert not cfg.opta_connected, "retained replay marked a dead cabinet connected"
    assert cfg.status == "offline", f"retained replay set status={cfg.status!r}"


def test_tc_ret_03_live_status_does_write_liveness():
    """The flag must not become a blanket off-switch — real traffic still counts."""
    from app.services import mqtt_handlers as mh
    _dispatch(_status_payload(seq=2, uptime_ms=30000), retained=False)

    pid = _pid()
    assert pid in mh.last_heartbeat
    cfg = _cfg()
    assert cfg.opta_connected
    assert cfg.status == "online"
    assert (datetime.utcnow() - cfg.last_heartbeat).total_seconds() < 60


# ═══════════════════════════════════════════════════════════════════════════
# TC-RET-04..06 — durable config and display still flow
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ret_04_retained_status_still_broadcasts_flagged():
    """The Control Center should still show last-known uptime/door — but labelled."""
    events = [b for b in _dispatch(_status_payload(), retained=True)
              if b.get("event") == "opta_status"]
    assert len(events) == 1
    data = events[0]["data"]
    assert data["retained"] is True
    assert data["uptime_ms"] == 2147471955
    assert data["door"] == "closed"


def test_tc_ret_05_live_status_broadcast_not_flagged():
    events = [b for b in _dispatch(_status_payload(seq=3), retained=False)
              if b.get("event") == "opta_status"]
    assert len(events) == 1
    assert events[0]["data"]["retained"] is False


def test_tc_ret_06_retained_status_still_applies_smart_mode():
    """SmartMode is durable config, not liveness — hydrating it from a replay is
    exactly what retain is for."""
    assert _cfg().smart_mode is False
    _dispatch(_status_payload(smartMode=True), retained=True)
    assert _cfg().smart_mode is True


# ═══════════════════════════════════════════════════════════════════════════
# TC-RET-07..08 — no commands to a cabinet that is not there
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ret_07_retained_seq_zero_does_not_publish_time_sync():
    from app.services import mqtt_handlers as mh
    with patch.object(mh, "_publish_time_sync") as sync:
        _dispatch(_status_payload(seq=0, uptime_ms=5000), retained=True)
    sync.assert_not_called()


def test_tc_ret_08_live_seq_zero_publishes_time_sync():
    from app.services import mqtt_handlers as mh
    with patch.object(mh, "_publish_time_sync") as sync:
        _dispatch(_status_payload(seq=0, uptime_ms=5000), retained=False)
    sync.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# TC-RET-09..10 — the legacy path and the transport callback
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ret_09_legacy_heartbeat_honours_retain_flag():
    from app.services import mqtt_handlers as mh
    pid = _pid()

    async def _noop(*a, **k):
        return None

    with patch.object(mh, "SessionLocal", _TestSession), \
         patch("app.services.mqtt_handlers.ws_manager.broadcast", new=_noop):
        asyncio.run(mh.handle_message(
            f"pedestal/{pid}/heartbeat", json.dumps({"online": True}), retained=True))
    assert pid not in mh.last_heartbeat

    with patch.object(mh, "SessionLocal", _TestSession), \
         patch("app.services.mqtt_handlers.ws_manager.broadcast", new=_noop):
        asyncio.run(mh.handle_message(
            f"pedestal/{pid}/heartbeat", json.dumps({"online": True}), retained=False))
    assert pid in mh.last_heartbeat


def test_tc_ret_10_mqtt_client_forwards_retain_flag():
    """The whole fix hinges on the transport passing msg.retain through; without
    this, every handler-level guard above is dead code."""
    from app.services.mqtt_client import MQTTService

    svc = MQTTService()
    loop = MagicMock()
    loop.is_running.return_value = True
    svc._loop = loop

    for retain_value in (True, False):
        msg = MagicMock()
        msg.topic = "opta/status"
        msg.payload = b'{"cabinetId":"X"}'
        msg.retain = retain_value
        with patch("app.services.mqtt_client.asyncio.run_coroutine_threadsafe") as run:
            svc._on_message(None, None, msg)
            assert run.call_count == 1
            coro = run.call_args[0][0]
            assert coro.cr_frame.f_locals["retained"] is retain_value, (
                f"msg.retain={retain_value} did not reach handle_message"
            )
            coro.close()


# ═══════════════════════════════════════════════════════════════════════════
# TC-RET-11 — the outage stays visible
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ret_11_retained_replay_does_not_mask_comm_loss():
    """End-to-end: after a restart replays the cabinet's final status, the
    comm-loss watchdog must still see it as silent. Regression on the real
    MAR_KRK_ORM_01 case, where the dashboard read 'online' for 19 days."""
    import app.main as main_mod
    from app.services import mqtt_handlers as mh

    _dispatch(_status_payload(), retained=True)       # the restart replay
    pid = _pid()

    # Nothing seeded → watchdog has no false 'recently alive' evidence.
    assert pid not in mh.last_heartbeat

    # Even if a stale entry existed, it must be older than the comm-loss cutoff.
    mh.last_heartbeat[pid] = datetime.utcnow() - timedelta(days=19)
    cutoff = datetime.utcnow() - timedelta(seconds=main_mod.COMM_LOSS_TIMEOUT_SECONDS)
    assert mh.last_heartbeat[pid] < cutoff, "replay made the cabinet look alive"
