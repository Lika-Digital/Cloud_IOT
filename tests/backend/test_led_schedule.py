"""
Daily LED Schedule — Verification Tests (v3.10)
================================================

Coverage for the per-pedestal LED schedule API + the asyncio scheduler tick.

Test IDs:
  TC-LS-01  PUT creates a schedule and the row round-trips through GET
  TC-LS-02  GET returns sane defaults when no schedule exists for the pedestal
  TC-LS-03  PUT with invalid HH:MM returns 400
  TC-LS-04  Scheduler fires LED on at the configured on_time
  TC-LS-05  Scheduler fires LED off at the configured off_time
  TC-LS-06  Scheduler does not fire on a day not in days_of_week
  TC-LS-07  Scheduler does not double-fire within the same minute
  TC-LS-08  Scheduler does not fire when enabled=False
  TC-LS-09  POST /test sends an LED command immediately
  TC-LS-10  DELETE removes the schedule and prevents subsequent fires
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


TEST_DB = "sqlite:///./tests/test_pedestal.db"
_test_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


@pytest.fixture(scope="module", autouse=True)
def _dispose_engine():
    yield
    _test_engine.dispose()


@pytest.fixture(autouse=True)
def _reset_dedup_dict():
    """Each test runs in a clean dedup state so the order of tests doesn't
    affect whether a fire is suppressed."""
    from app.services import led_scheduler as ls
    ls._led_schedule_last_fired.clear()
    yield
    ls._led_schedule_last_fired.clear()


# ── helpers ──────────────────────────────────────────────────────────────────

def _ensure_pedestal() -> int:
    """Pin pedestal_id=1 with a known opta_client_id every test.

    Other test files (auto-discovery, breakers, valves, etc.) freely create
    and update PedestalConfig rows on the same shared test DB. We don't
    care what they did — we always force pid=1's opta_client_id back to
    MAR_TEST_LED_01 so the LED publishes land on opta/cmd/led not on
    pedestal/1/cmd/led."""
    from app.models.pedestal import Pedestal
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        if not db.get(Pedestal, 1):
            db.add(Pedestal(id=1, name="Test Pedestal", location="dev", data_mode="real"))
            db.commit()
        cfg = db.query(PedestalConfig).filter_by(pedestal_id=1).first()
        if cfg is None:
            db.add(PedestalConfig(pedestal_id=1, opta_client_id="MAR_TEST_LED_01"))
        else:
            cfg.opta_client_id = "MAR_TEST_LED_01"
        db.commit()
        return 1
    finally:
        db.close()


def _seed_schedule(**overrides) -> None:
    """Insert / replace the schedule row directly without hitting the API."""
    from app.models.led_schedule import LedSchedule
    db = _TestSession()
    try:
        s = db.query(LedSchedule).filter_by(pedestal_id=1).first()
        if s is None:
            s = LedSchedule(
                pedestal_id=1,
                enabled=True,
                on_time="20:00",
                off_time="23:00",
                color="green",
                days_of_week="0,1,2,3,4,5,6",
            )
            db.add(s)
        for k, v in overrides.items():
            setattr(s, k, v)
        db.commit()
    finally:
        db.close()


def _delete_schedule() -> None:
    from app.models.led_schedule import LedSchedule
    db = _TestSession()
    try:
        db.query(LedSchedule).filter_by(pedestal_id=1).delete()
        db.commit()
    finally:
        db.close()


def _run_tick(now_local_str: str, weekday_iso: str = "2026-04-27") -> tuple[int, list]:
    """Run a single scheduler tick at a given marina-local time. Default day
    2026-04-27 is a Monday (weekday=0). Returns (fire_count, mqtt_publishes)."""
    publishes: list[tuple[str, str]] = []

    def capture_publish(topic, payload, *a, **kw):
        publishes.append((topic, payload))

    # Build a UTC datetime such that converting through the configured TZ
    # (UTC by default in tests) gives the desired local time.
    when_utc = datetime.fromisoformat(f"{weekday_iso}T{now_local_str}:00").replace(tzinfo=timezone.utc)

    db = _TestSession()
    try:
        from app.services import led_scheduler as ls
        with (
            patch("app.services.mqtt_client.mqtt_service.publish", side_effect=capture_publish),
            patch("app.services.led_scheduler.ws_manager", create=True),
        ):
            # ws_manager.broadcast is referenced inside _publish_led; patch
            # the whole symbol on the imported alias inside the helper.
            with patch("app.services.websocket_manager.ws_manager.broadcast",
                       new=lambda msg: asyncio.sleep(0)):
                fired = asyncio.run(ls.tick_once(db, now_utc=when_utc))
    finally:
        db.close()
    return fired, publishes


# ── TC-LS-01 ─────────────────────────────────────────────────────────────────

def test_put_creates_schedule_and_get_returns_it(client, auth_headers):
    pid = _ensure_pedestal()
    _delete_schedule()

    body = {
        "enabled": True,
        "on_time": "20:30",
        "off_time": "22:45",
        "color": "blue",
        "days_of_week": "1,2,3,4,5",
    }
    r = client.put(f"/api/pedestals/{pid}/led-schedule", json=body, headers=auth_headers)
    assert r.status_code == 200
    out = r.json()
    assert out["on_time"] == "20:30"
    assert out["off_time"] == "22:45"
    assert out["color"] == "blue"
    assert out["days_of_week"] == "1,2,3,4,5"
    assert out["enabled"] is True

    r2 = client.get(f"/api/pedestals/{pid}/led-schedule", headers=auth_headers)
    assert r2.status_code == 200
    g = r2.json()
    assert g["on_time"] == "20:30"
    assert g["color"] == "blue"


# ── TC-LS-02 ─────────────────────────────────────────────────────────────────

def test_get_returns_defaults_when_no_schedule(client, auth_headers):
    pid = _ensure_pedestal()
    _delete_schedule()
    r = client.get(f"/api/pedestals/{pid}/led-schedule", headers=auth_headers)
    assert r.status_code == 200
    g = r.json()
    assert g["enabled"] is False
    assert g["on_time"] is None
    assert g["off_time"] is None
    assert g["color"] == "green"
    assert g["days_of_week"] == "0,1,2,3,4,5,6"


# ── TC-LS-03 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("on_time, off_time, expect_field", [
    ("25:00", "23:00", "on_time"),
    ("20:00", "23:99", "off_time"),
    ("8:00", "23:00", "on_time"),     # missing leading zero
    ("20:00", "23",    "off_time"),
])
def test_put_invalid_hhmm_returns_400(client, auth_headers, on_time, off_time, expect_field):
    pid = _ensure_pedestal()
    body = {
        "enabled": True,
        "on_time": on_time,
        "off_time": off_time,
        "color": "green",
        "days_of_week": "0,1,2,3,4,5,6",
    }
    r = client.put(f"/api/pedestals/{pid}/led-schedule", json=body, headers=auth_headers)
    assert r.status_code == 400
    assert expect_field in r.json()["detail"]


# ── TC-LS-04 ─────────────────────────────────────────────────────────────────

def test_scheduler_fires_on_at_configured_time():
    _ensure_pedestal()
    _seed_schedule(on_time="20:00", off_time="23:00",
                   days_of_week="0,1,2,3,4,5,6", enabled=True, color="green")
    fired, publishes = _run_tick("20:00")
    assert fired == 1
    led_topics = [p for p in publishes if p[0] == "opta/cmd/led"]
    assert len(led_topics) == 1
    payload = json.loads(led_topics[0][1])
    assert payload["state"] == "on"
    assert payload["color"] == "green"
    assert payload["cabinetId"] == "MAR_TEST_LED_01"


# ── TC-LS-05 ─────────────────────────────────────────────────────────────────

def test_scheduler_fires_off_at_configured_time():
    _ensure_pedestal()
    _seed_schedule(on_time="20:00", off_time="23:00",
                   days_of_week="0,1,2,3,4,5,6", enabled=True, color="green")
    fired, publishes = _run_tick("23:00")
    assert fired == 1
    payload = json.loads(publishes[0][1])
    assert payload["state"] == "off"


# ── TC-LS-06 ─────────────────────────────────────────────────────────────────

def test_scheduler_skips_day_not_in_days_of_week():
    _ensure_pedestal()
    # Only Tuesday (=1). 2026-04-27 is Monday (=0) → must NOT fire.
    _seed_schedule(on_time="20:00", off_time="23:00",
                   days_of_week="1", enabled=True, color="green")
    fired, publishes = _run_tick("20:00", weekday_iso="2026-04-27")
    assert fired == 0
    assert publishes == []


# ── TC-LS-07 ─────────────────────────────────────────────────────────────────

def test_scheduler_dedups_within_same_minute():
    _ensure_pedestal()
    _seed_schedule(on_time="20:00", off_time="23:00",
                   days_of_week="0,1,2,3,4,5,6", enabled=True, color="green")
    fired1, _ = _run_tick("20:00")
    fired2, _ = _run_tick("20:00")
    assert fired1 == 1
    assert fired2 == 0   # already fired this on-window today


# ── TC-LS-08 ─────────────────────────────────────────────────────────────────

def test_scheduler_skips_when_disabled():
    _ensure_pedestal()
    _seed_schedule(on_time="20:00", off_time="23:00",
                   days_of_week="0,1,2,3,4,5,6", enabled=False, color="green")
    fired, publishes = _run_tick("20:00")
    assert fired == 0
    assert publishes == []


# ── TC-LS-09 ─────────────────────────────────────────────────────────────────

def test_test_endpoint_sends_led_command_immediately(client, auth_headers):
    pid = _ensure_pedestal()
    _seed_schedule(on_time="20:00", off_time="23:00",
                   days_of_week="0,1,2,3,4,5,6", enabled=True, color="red")
    publishes: list[tuple[str, str]] = []

    def capture_publish(topic, payload, *a, **kw):
        publishes.append((topic, payload))

    with patch("app.services.mqtt_client.mqtt_service.publish", side_effect=capture_publish):
        r = client.post(f"/api/pedestals/{pid}/led-schedule/test", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "led_test_sent"
    assert any(p[0] == "opta/cmd/led" for p in publishes)
    payload = json.loads([p for p in publishes if p[0] == "opta/cmd/led"][0][1])
    assert payload["color"] == "red"
    assert payload["state"] == "on"


def test_test_endpoint_returns_404_when_no_schedule(client, auth_headers):
    pid = _ensure_pedestal()
    _delete_schedule()
    r = client.post(f"/api/pedestals/{pid}/led-schedule/test", headers=auth_headers)
    assert r.status_code == 404


# ── TC-LS-10 ─────────────────────────────────────────────────────────────────

def test_delete_removes_schedule_and_stops_fires(client, auth_headers):
    pid = _ensure_pedestal()
    _seed_schedule(on_time="20:00", off_time="23:00",
                   days_of_week="0,1,2,3,4,5,6", enabled=True, color="green")

    r = client.delete(f"/api/pedestals/{pid}/led-schedule", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    fired, publishes = _run_tick("20:00")
    assert fired == 0
    assert publishes == []
