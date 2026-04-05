"""
hardware_monitor.py — on-demand NUC hardware statistics collector.

No background threads.  Stats are collected when the API endpoint is called.
Automatic downgrade actions are applied when critical thresholds are first crossed.

Public API
----------
get_hardware_stats()   → dict   — collect all psutil stats (< 500ms target)
check_alarms(stats)    → list   — pure: which params exceed thresholds
evaluate_and_act(alarms) → list — dedup, apply downgrade, log actions
get_action_log()       → list   — newest-first action history (max 100)
is_rtsp_suspended()    → bool   — True if RTSP grab is thermally suspended
"""
import gc
import logging
import os
import time
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ─── Protected processes — must never be adjusted or killed ──────────────────
PROTECTED_PROCESSES = frozenset({
    "uvicorn", "nginx", "cloudflared", "tailscaled", "mosquitto", "sshd",
})

# ─── Module-level state ───────────────────────────────────────────────────────
_action_log: deque = deque(maxlen=100)   # newest first (appendleft)
_known_critical: set = set()             # params with an active critical alarm
_temp_suspend_until: float = 0.0         # epoch seconds for RTSP suspension


# ─── RTSP suspension (checked by berth_analyzer before grabbing frames) ──────

def is_rtsp_suspended() -> bool:
    """Return True if RTSP frame grab is suspended (thermal protection active)."""
    return time.time() < _temp_suspend_until


def _suspend_rtsp(seconds: int = 60) -> None:
    global _temp_suspend_until
    _temp_suspend_until = time.time() + seconds


# ─── Formatting helpers ───────────────────────────────────────────────────────

def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _fmt_uptime(secs: int) -> str:
    days  = secs // 86400
    hours = (secs % 86400) // 3600
    mins  = (secs % 3600) // 60
    parts: list[str] = []
    if days:  parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts) or "0m"


# ─── Stats collection ─────────────────────────────────────────────────────────

def get_hardware_stats() -> dict:
    """
    Collect all NUC hardware stats in a single on-demand call.
    Targets < 500ms.  Returns {"available": False} if psutil is missing.
    """
    try:
        import psutil
    except ImportError:
        return {"available": False, "error": "psutil not installed"}

    from app.config import settings

    t0 = time.perf_counter()

    # ── CPU ───────────────────────────────────────────────────────────────────
    cpu_per_core = psutil.cpu_percent(percpu=True, interval=0.1)
    cpu_overall  = sum(cpu_per_core) / len(cpu_per_core) if cpu_per_core else 0.0
    cpu_freq     = psutil.cpu_freq()
    cpu_freq_pct = 0.0
    if cpu_freq and cpu_freq.max > 0:
        cpu_freq_pct = (cpu_freq.current / cpu_freq.max) * 100.0

    # ── Load average ──────────────────────────────────────────────────────────
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = 0.0

    # ── Memory ────────────────────────────────────────────────────────────────
    mem = psutil.virtual_memory()

    # ── Disk (root filesystem) ────────────────────────────────────────────────
    try:
        disk = psutil.disk_usage("/")
    except Exception:
        disk = None

    # ── CPU temperature ───────────────────────────────────────────────────────
    cpu_temp: float | None = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for key in ("coretemp", "k10temp", "acpitz", "cpu_thermal", "x86_pkg_temp"):
                if key in temps and temps[key]:
                    cpu_temp = temps[key][0].current
                    break
            if cpu_temp is None:
                for entries in temps.values():
                    if entries:
                        cpu_temp = entries[0].current
                        break
    except (AttributeError, NotImplementedError):
        pass

    # ── Network interfaces ────────────────────────────────────────────────────
    net_stats = psutil.net_if_stats()
    net_io    = psutil.net_io_counters(pernic=True)
    net_addrs = psutil.net_if_addrs()

    interfaces = []
    for iface, st in net_stats.items():
        if iface == "lo":
            continue
        addrs = net_addrs.get(iface, [])
        ip = next(
            (a.address for a in addrs if hasattr(a, "family") and a.family.name == "AF_INET"),
            None,
        )
        io = net_io.get(iface)
        interfaces.append({
            "name":         iface,
            "up":           st.isup,
            "speed":        st.speed,
            "ip":           ip,
            "bytes_sent":    io.bytes_sent    if io else 0,
            "bytes_recv":    io.bytes_recv    if io else 0,
            "bytes_sent_hr": _fmt_bytes(io.bytes_sent) if io else "0 B",
            "bytes_recv_hr": _fmt_bytes(io.bytes_recv) if io else "0 B",
        })

    # ── Uptime ────────────────────────────────────────────────────────────────
    uptime_secs = int(time.time() - psutil.boot_time())

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.debug("hardware_monitor: stats in %.1f ms", elapsed_ms)

    temp_warn = settings.hw_temp_max * settings.hw_temp_warning_pct / 100.0
    temp_crit = settings.hw_temp_max * settings.hw_temp_critical_pct / 100.0

    return {
        "available":     True,
        "collected_at":  datetime.now(timezone.utc).isoformat(),
        "elapsed_ms":    round(elapsed_ms, 1),
        "rtsp_suspended": is_rtsp_suspended(),
        # CPU
        "cpu_percent":  round(cpu_overall, 1),
        "cpu_per_core": [round(v, 1) for v in cpu_per_core],
        "cpu_freq_pct": round(cpu_freq_pct, 1),
        "cpu_freq_mhz": round(cpu_freq.current, 0) if cpu_freq else None,
        # Load
        "load_1":  round(load1, 2),
        "load_5":  round(load5, 2),
        "load_15": round(load15, 2),
        # Memory
        "mem_total":    mem.total,
        "mem_used":     mem.used,
        "mem_free":     mem.available,
        "mem_percent":  round(mem.percent, 1),
        "mem_total_hr": _fmt_bytes(mem.total),
        "mem_used_hr":  _fmt_bytes(mem.used),
        "mem_free_hr":  _fmt_bytes(mem.available),
        # Disk
        "disk_total":    disk.total    if disk else 0,
        "disk_used":     disk.used     if disk else 0,
        "disk_free":     disk.free     if disk else 0,
        "disk_percent":  round(disk.percent, 1) if disk else 0.0,
        "disk_total_hr": _fmt_bytes(disk.total) if disk else "N/A",
        "disk_used_hr":  _fmt_bytes(disk.used)  if disk else "N/A",
        "disk_free_hr":  _fmt_bytes(disk.free)  if disk else "N/A",
        "disk_path":     "/dev/mapper/ubuntu--vg-ubuntu--lv",
        # Temperature
        "cpu_temp":     round(cpu_temp, 1) if cpu_temp is not None else None,
        "cpu_temp_max": settings.hw_temp_max,
        # Uptime
        "uptime_secs": uptime_secs,
        "uptime":      _fmt_uptime(uptime_secs),
        # Network
        "interfaces": interfaces,
        # Thresholds (sent to frontend for gauge rendering)
        "thresholds": {
            "cpu_warning":   settings.hw_cpu_warning,
            "cpu_critical":  settings.hw_cpu_critical,
            "mem_warning":   settings.hw_mem_warning,
            "mem_critical":  settings.hw_mem_critical,
            "disk_warning":  settings.hw_disk_warning,
            "disk_critical": settings.hw_disk_critical,
            "temp_warning":  round(temp_warn, 1),
            "temp_critical": round(temp_crit, 1),
        },
    }


# ─── Alarm detection ──────────────────────────────────────────────────────────

def check_alarms(stats: dict) -> list[dict]:
    """
    Pure function — check all monitored parameters against thresholds.
    Returns list of active alarms sorted by severity (critical first).
    """
    if not stats.get("available"):
        return []

    thr = stats["thresholds"]
    alarms: list[dict] = []

    def _check(param: str, label: str, value: float | None,
                warn: float, crit: float, unit: str):
        if value is None:
            return
        if value >= crit:
            alarms.append({
                "level": "critical", "param": param, "label": label,
                "value": value, "threshold": crit, "unit": unit,
            })
        elif value >= warn:
            alarms.append({
                "level": "warning", "param": param, "label": label,
                "value": value, "threshold": warn, "unit": unit,
            })

    _check("cpu",         "CPU Usage",       stats["cpu_percent"],  thr["cpu_warning"],  thr["cpu_critical"],  "%")
    _check("memory",      "Memory Usage",    stats["mem_percent"],  thr["mem_warning"],  thr["mem_critical"],  "%")
    _check("disk",        "Disk Usage",      stats["disk_percent"], thr["disk_warning"], thr["disk_critical"], "%")
    _check("temperature", "CPU Temperature", stats["cpu_temp"],     thr["temp_warning"], thr["temp_critical"], "°C")

    # Critical first
    alarms.sort(key=lambda a: 0 if a["level"] == "critical" else 1)
    return alarms


# ─── Automatic downgrade ──────────────────────────────────────────────────────

def evaluate_and_act(alarms: list[dict]) -> list[dict]:
    """
    Compare current critical alarms against _known_critical.
    For newly-triggered ones, apply downgrade action and return new log entries.
    Clears _known_critical entries that have resolved.
    """
    global _known_critical
    current_critical = {a["param"] for a in alarms if a["level"] == "critical"}
    new_params        = current_critical - _known_critical
    _known_critical   = current_critical

    new_entries: list[dict] = []
    for alarm in alarms:
        if alarm["level"] == "critical" and alarm["param"] in new_params:
            entry = _apply_downgrade(alarm)
            if entry:
                new_entries.append(entry)
    return new_entries


def _apply_downgrade(alarm: dict) -> dict | None:
    """Execute a single downgrade action and add to the action log."""
    param   = alarm["param"]
    value   = alarm["value"]
    action_taken: str | None = None
    result: str | None       = None

    try:
        import psutil

        if param == "cpu":
            cloud_procs: list[tuple] = []
            for proc in psutil.process_iter(["pid", "name", "username", "cpu_percent"]):
                try:
                    info = proc.info
                    uname = info.get("username") or ""
                    if "cloud_iot" in uname:
                        cloud_procs.append((info["cpu_percent"] or 0.0, info["pid"], info["name"], proc))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not cloud_procs:
                action_taken = "CPU Alarm 2: no cloud_iot processes found"
                result = "no_processes"
            else:
                cloud_procs.sort(reverse=True)
                _, pid, name, proc_obj = cloud_procs[0]
                base = (name or "").split("/")[-1]

                if base in PROTECTED_PROCESSES or any(p in base for p in PROTECTED_PROCESSES):
                    action_taken = (
                        f"CPU Alarm 2: highest process '{base}' (PID {pid}) is PROTECTED — "
                        "not adjusted; recommend manual intervention"
                    )
                    result = "skipped_protected"
                    logger.warning("hardware_monitor: %s", action_taken)
                else:
                    try:
                        p = psutil.Process(pid)
                        prev = p.nice()
                        if prev < 10:
                            p.nice(10)
                        action_taken = f"CPU Alarm 2: set nice=10 on '{base}' (PID {pid}, was {prev})"
                        result = "nice_applied"
                        logger.info("hardware_monitor: %s", action_taken)
                    except (psutil.NoSuchProcess, psutil.AccessDenied, PermissionError) as exc:
                        action_taken = f"CPU Alarm 2: could not nice '{base}' (PID {pid}): {exc}"
                        result = "nice_failed"
                        logger.warning("hardware_monitor: %s", action_taken)

        elif param == "memory":
            freed = gc.collect()
            action_taken = f"Memory Alarm 2 ({value:.1f}%): gc.collect() freed {freed} objects"
            result = f"gc_freed_{freed}"
            logger.info("hardware_monitor: %s", action_taken)

        elif param == "temperature":
            if is_rtsp_suspended():
                resume_str = datetime.fromtimestamp(_temp_suspend_until).strftime("%H:%M:%S")
                action_taken = f"Temperature Alarm 2: RTSP grab already suspended until {resume_str}"
                result = "already_suspended"
            else:
                _suspend_rtsp(60)
                resume_str = datetime.fromtimestamp(_temp_suspend_until).strftime("%H:%M:%S")
                action_taken = (
                    f"Temperature Alarm 2 ({value:.1f}°C ≥ threshold): "
                    f"RTSP frame grab suspended 60s (resumes {resume_str})"
                )
                result = "rtsp_suspended"
                logger.info("hardware_monitor: %s", action_taken)

        elif param == "disk":
            action_taken = f"Disk Alarm 2 ({value:.1f}%): display-only — manual cleanup required"
            result = "display_only"
            logger.warning("hardware_monitor: %s", action_taken)

    except Exception as exc:
        action_taken = f"Alarm 2 ({param}): downgrade action failed: {exc}"
        result = "exception"
        logger.error("hardware_monitor: %s", action_taken, exc_info=True)

    if action_taken:
        entry = {
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "param":       param,
            "value":       value,
            "alarm_level": alarm["level"],
            "action":      action_taken,
            "result":      result,
        }
        _action_log.appendleft(entry)
        return entry

    return None


def get_action_log() -> list[dict]:
    """Return automatic action history, newest first (max 100 entries)."""
    return list(_action_log)
