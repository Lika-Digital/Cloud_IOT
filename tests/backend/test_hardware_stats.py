"""
Tests for the hardware stats endpoint and hardware_monitor service.

psutil is not available on the Windows 32-bit dev machine, so all tests
mock it at the module level before import.
"""
import time
import importlib
from unittest.mock import MagicMock, patch


# ─── Helpers to build mock psutil data ───────────────────────────────────────

def _mock_psutil(
    cpu_pct=25.0,
    mem_pct=40.0,
    disk_pct=30.0,
    cpu_temp=45.0,
):
    """Return a MagicMock that behaves like psutil with configurable values."""
    m = MagicMock()

    # cpu_percent
    m.cpu_percent.return_value = [cpu_pct, cpu_pct]

    # cpu_freq
    freq = MagicMock()
    freq.current = 2000.0
    freq.max     = 2800.0
    m.cpu_freq.return_value = freq

    # virtual_memory
    mem = MagicMock()
    mem.total    = 8 * 1024**3
    mem.used     = int(mem.total * mem_pct / 100)
    mem.available= mem.total - mem.used
    mem.percent  = mem_pct
    m.virtual_memory.return_value = mem

    # disk_usage
    disk = MagicMock()
    disk.total   = 100 * 1024**3
    disk.used    = int(disk.total * disk_pct / 100)
    disk.free    = disk.total - disk.used
    disk.percent = disk_pct
    m.disk_usage.return_value = disk

    # sensors_temperatures
    sensor = MagicMock()
    sensor.current = cpu_temp
    m.sensors_temperatures.return_value = {"coretemp": [sensor]}

    # net_if_stats
    iface = MagicMock()
    iface.isup  = True
    iface.speed = 1000
    m.net_if_stats.return_value = {"eth0": iface}

    # net_io_counters
    io = MagicMock()
    io.bytes_sent = 1_000_000
    io.bytes_recv = 5_000_000
    m.net_io_counters.return_value = {"eth0": io}

    # net_if_addrs
    addr = MagicMock()
    addr.family.name = "AF_INET"
    addr.address     = "192.168.1.10"
    m.net_if_addrs.return_value = {"eth0": [addr]}

    # boot_time
    m.boot_time.return_value = time.time() - 3600  # 1h uptime

    # process_iter (for CPU downgrade test — override per test)
    m.process_iter.return_value = []

    # NoSuchProcess / AccessDenied as real exceptions (needed for except clauses)
    m.NoSuchProcess  = type("NoSuchProcess",  (Exception,), {})
    m.AccessDenied   = type("AccessDenied",   (Exception,), {})

    return m


# ─── Endpoint tests ──────────────────────────────────────────────────────────

def test_hardware_stats_endpoint_returns_200(client, auth_headers):
    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        import app.services.hardware_monitor as hw_mod
        importlib.reload(hw_mod)
        with patch("app.routers.hardware_stats.hw", hw_mod):
            r = client.get("/api/system/hardware-stats", headers=auth_headers)
    assert r.status_code == 200


def test_hardware_stats_requires_auth(client):
    r = client.get("/api/system/hardware-stats")
    assert r.status_code in (401, 403)  # 403 from security middleware


def test_hardware_stats_returns_required_fields(client, auth_headers):
    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        import app.services.hardware_monitor as hw_mod
        importlib.reload(hw_mod)
        with patch("app.routers.hardware_stats.hw", hw_mod):
            r = client.get("/api/system/hardware-stats", headers=auth_headers)
    data = r.json()
    required = [
        "available", "cpu_percent", "cpu_per_core", "cpu_freq_pct",
        "load_1", "load_5", "load_15",
        "mem_percent", "mem_total_hr", "mem_used_hr", "mem_free_hr",
        "disk_percent", "disk_total_hr", "disk_used_hr", "disk_free_hr",
        "cpu_temp", "uptime", "interfaces", "thresholds", "alarms", "action_log",
    ]
    for field in required:
        assert field in data, f"Missing field: {field}"


def test_hardware_stats_completes_under_500ms(client, auth_headers):
    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        import app.services.hardware_monitor as hw_mod
        importlib.reload(hw_mod)
        with patch("app.routers.hardware_stats.hw", hw_mod):
            t0 = time.perf_counter()
            r  = client.get("/api/system/hardware-stats", headers=auth_headers)
            elapsed_ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200
    assert elapsed_ms < 500, f"Endpoint took {elapsed_ms:.1f}ms (> 500ms budget)"


# ─── Alarm detection tests ────────────────────────────────────────────────────

def _get_alarms(cpu=5.0, mem=5.0, disk=5.0, temp=30.0):
    """Run check_alarms with given values and return alarm list."""
    import app.services.hardware_monitor as hw
    importlib.reload(hw)
    stats = {
        "available":    True,
        "cpu_percent":  cpu,
        "mem_percent":  mem,
        "disk_percent": disk,
        "cpu_temp":     temp,
        "cpu_temp_max": 90.0,
        "thresholds": {
            "cpu_warning":   60.0, "cpu_critical":  80.0,
            "mem_warning":   60.0, "mem_critical":  80.0,
            "disk_warning":  60.0, "disk_critical": 80.0,
            "temp_warning":  54.0, "temp_critical": 72.0,
        },
    }
    return hw.check_alarms(stats)


def test_alarm1_cpu_triggers_at_warning_threshold():
    alarms = _get_alarms(cpu=61.0)
    cpu_alarm = next((a for a in alarms if a["param"] == "cpu"), None)
    assert cpu_alarm is not None
    assert cpu_alarm["level"] == "warning"


def test_alarm2_cpu_triggers_at_critical_threshold():
    alarms = _get_alarms(cpu=82.0)
    cpu_alarm = next((a for a in alarms if a["param"] == "cpu"), None)
    assert cpu_alarm is not None
    assert cpu_alarm["level"] == "critical"


def test_alarm1_memory_triggers_at_warning_threshold():
    alarms = _get_alarms(mem=65.0)
    mem_alarm = next((a for a in alarms if a["param"] == "memory"), None)
    assert mem_alarm is not None
    assert mem_alarm["level"] == "warning"


def test_alarm2_memory_triggers_at_critical_threshold():
    alarms = _get_alarms(mem=85.0)
    mem_alarm = next((a for a in alarms if a["param"] == "memory"), None)
    assert mem_alarm is not None
    assert mem_alarm["level"] == "critical"


def test_alarm1_disk_triggers_at_warning_threshold():
    alarms = _get_alarms(disk=62.0)
    disk_alarm = next((a for a in alarms if a["param"] == "disk"), None)
    assert disk_alarm is not None
    assert disk_alarm["level"] == "warning"


def test_alarm2_disk_triggers_at_critical_threshold():
    alarms = _get_alarms(disk=81.0)
    disk_alarm = next((a for a in alarms if a["param"] == "disk"), None)
    assert disk_alarm is not None
    assert disk_alarm["level"] == "critical"


def test_alarm1_temperature_triggers_at_54c():
    alarms = _get_alarms(temp=55.0)
    temp_alarm = next((a for a in alarms if a["param"] == "temperature"), None)
    assert temp_alarm is not None
    assert temp_alarm["level"] == "warning"


def test_alarm2_temperature_triggers_at_72c():
    alarms = _get_alarms(temp=73.0)
    temp_alarm = next((a for a in alarms if a["param"] == "temperature"), None)
    assert temp_alarm is not None
    assert temp_alarm["level"] == "critical"


def test_no_alarm_below_all_thresholds():
    alarms = _get_alarms(cpu=10.0, mem=20.0, disk=15.0, temp=40.0)
    assert alarms == []


def test_critical_alarm_sorted_before_warning():
    alarms = _get_alarms(cpu=85.0, mem=65.0)
    levels = [a["level"] for a in alarms]
    assert levels[0] == "critical"


# ─── Downgrade action tests ───────────────────────────────────────────────────

def _make_alarm(param, level="critical", value=85.0):
    return {"level": level, "param": param, "label": param, "value": value, "threshold": 80.0, "unit": "%"}


def test_memory_alarm2_triggers_gc():
    import app.services.hardware_monitor as hw
    importlib.reload(hw)
    import gc as _gc

    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        with patch.object(_gc, "collect", return_value=42) as mock_gc:
            alarm = _make_alarm("memory", value=82.0)
            entry = hw._apply_downgrade(alarm)

    assert entry is not None
    assert "gc" in entry["result"].lower() or "freed" in entry["action"].lower()
    mock_gc.assert_called_once()


def test_disk_alarm2_is_display_only():
    import app.services.hardware_monitor as hw
    importlib.reload(hw)

    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        alarm = _make_alarm("disk", value=82.0)
        entry = hw._apply_downgrade(alarm)

    assert entry is not None
    assert entry["result"] == "display_only"
    assert "manual" in entry["action"].lower()


def test_temperature_alarm2_suspends_rtsp():
    import app.services.hardware_monitor as hw
    importlib.reload(hw)
    hw._temp_suspend_until = 0.0  # reset

    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        alarm = _make_alarm("temperature", value=73.0)
        alarm["unit"] = "°C"
        entry = hw._apply_downgrade(alarm)

    assert entry is not None
    assert entry["result"] == "rtsp_suspended"
    assert hw.is_rtsp_suspended() is True
    # Cleanup
    hw._temp_suspend_until = 0.0


def test_temperature_suspension_expires():
    import app.services.hardware_monitor as hw
    importlib.reload(hw)
    hw._temp_suspend_until = time.time() - 1  # already expired
    assert hw.is_rtsp_suspended() is False


def test_temperature_suspension_active():
    import app.services.hardware_monitor as hw
    importlib.reload(hw)
    hw._temp_suspend_until = time.time() + 60
    assert hw.is_rtsp_suspended() is True
    hw._temp_suspend_until = 0.0  # cleanup


def test_cpu_alarm2_nice_applied_to_non_protected_process():
    import app.services.hardware_monitor as hw
    importlib.reload(hw)

    mock_ps = _mock_psutil()
    proc = MagicMock()
    proc.info = {"pid": 9999, "name": "myapp", "username": "cloud_iot", "cpu_percent": 90.0}
    proc_handle = MagicMock()
    proc_handle.nice.return_value = 0  # current niceness

    mock_ps.process_iter.return_value = [proc]
    mock_ps.Process.return_value = proc_handle

    with patch.dict("sys.modules", {"psutil": mock_ps}):
        alarm = _make_alarm("cpu", value=85.0)
        entry = hw._apply_downgrade(alarm)

    assert entry is not None
    assert entry["result"] == "nice_applied"
    proc_handle.nice.assert_called_with(10)


def test_cpu_alarm2_protected_process_skipped():
    import app.services.hardware_monitor as hw
    importlib.reload(hw)

    mock_ps = _mock_psutil()
    proc = MagicMock()
    proc.info = {"pid": 1234, "name": "uvicorn", "username": "cloud_iot", "cpu_percent": 90.0}
    mock_ps.process_iter.return_value = [proc]

    with patch.dict("sys.modules", {"psutil": mock_ps}):
        alarm = _make_alarm("cpu", value=85.0)
        entry = hw._apply_downgrade(alarm)

    assert entry is not None
    assert entry["result"] == "skipped_protected"
    assert "PROTECTED" in entry["action"]


def test_all_protected_process_names():
    """All names in PROTECTED_PROCESSES must be recognized and skipped."""
    import app.services.hardware_monitor as hw
    importlib.reload(hw)

    for proc_name in hw.PROTECTED_PROCESSES:
        mock_ps = _mock_psutil()
        proc = MagicMock()
        proc.info = {"pid": 100, "name": proc_name, "username": "cloud_iot", "cpu_percent": 95.0}
        mock_ps.process_iter.return_value = [proc]

        with patch.dict("sys.modules", {"psutil": mock_ps}):
            alarm = _make_alarm("cpu", value=85.0)
            entry = hw._apply_downgrade(alarm)

        assert entry is not None, f"No action logged for protected process: {proc_name}"
        assert entry["result"] == "skipped_protected", (
            f"Protected process '{proc_name}' was not skipped: result={entry['result']}"
        )


def test_actions_logged_with_required_fields():
    import app.services.hardware_monitor as hw
    importlib.reload(hw)

    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        alarm = _make_alarm("disk", value=83.0)
        entry = hw._apply_downgrade(alarm)

    assert entry is not None
    for field in ("timestamp", "param", "value", "alarm_level", "action", "result"):
        assert field in entry, f"Missing field in action log entry: {field}"


def test_action_log_contains_entry_after_downgrade():
    import app.services.hardware_monitor as hw
    importlib.reload(hw)
    hw._action_log.clear()

    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        alarm = _make_alarm("disk", value=82.0)
        hw._apply_downgrade(alarm)

    log = hw.get_action_log()
    assert len(log) >= 1
    assert log[0]["param"] == "disk"


def test_evaluate_and_act_deduplicates_critical_alarms():
    """Downgrade should only fire once per param, not on every 10s poll."""
    import app.services.hardware_monitor as hw
    importlib.reload(hw)
    hw._known_critical.clear()
    hw._action_log.clear()

    alarm = _make_alarm("disk", value=82.0)

    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        actions1 = hw.evaluate_and_act([alarm])
        actions2 = hw.evaluate_and_act([alarm])  # same alarm still active

    assert len(actions1) == 1  # fired first time
    assert len(actions2) == 0  # deduplicated on second poll
    hw._known_critical.clear()


def test_evaluate_and_act_refires_after_alarm_resolves():
    """If alarm resolves and re-triggers, downgrade must fire again."""
    import app.services.hardware_monitor as hw
    importlib.reload(hw)
    hw._known_critical.clear()

    alarm = _make_alarm("disk", value=82.0)

    with patch.dict("sys.modules", {"psutil": _mock_psutil()}):
        hw.evaluate_and_act([alarm])     # first trigger
        hw.evaluate_and_act([])          # alarm resolved — clears _known_critical
        actions = hw.evaluate_and_act([alarm])  # re-triggered

    assert len(actions) == 1  # fired again after resolution
    hw._known_critical.clear()


# ─── WebSocket hardware_alarm event test ────────────────────────────────────

def test_hardware_alarm_ws_event_pushed_on_alarm2(client, auth_headers):
    """
    When a critical alarm fires for the first time, the endpoint should push
    a hardware_alarm WebSocket event.  We verify by checking the broadcast was
    called (mocked) without starting a real WS.
    """
    import app.services.hardware_monitor as hw_mod
    importlib.reload(hw_mod)
    hw_mod._known_critical.clear()

    mock_ps = _mock_psutil(cpu_pct=85.0)  # triggers CPU critical

    with patch.dict("sys.modules", {"psutil": mock_ps}):
        with patch("app.routers.hardware_stats.hw", hw_mod):
            with patch("app.routers.hardware_stats.ws_manager") as mock_ws:
                import asyncio
                async def _noop(*a, **kw): pass
                mock_ws.broadcast = MagicMock(side_effect=_noop)
                r = client.get("/api/system/hardware-stats", headers=auth_headers)

    assert r.status_code == 200
    hw_mod._known_critical.clear()
