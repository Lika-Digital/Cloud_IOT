"""
In-memory, thread-safe security monitor.

Tracks failed login attempts per IP for brute-force detection.
Also provides the SQL injection / XSS pattern list used by SecurityMiddleware.

Public API:
    record_login_failure(ip)   — call on every failed auth attempt
    record_login_success(ip)   — call on successful login (resets counter)
    check_brute_force(ip)      — True if ≥ THRESHOLD failures in WINDOW
    get_failure_count(ip)      — number of failures in current window
    SQL_INJECTION_PATTERNS     — list[re.Pattern] for query-string scanning
"""
import re
import threading
from collections import defaultdict
from datetime import datetime, timedelta

_WINDOW_SECONDS = 300   # 5-minute sliding window
_MAX_FAILURES   = 5     # failures before brute-force alarm is triggered

_lock: threading.Lock = threading.Lock()
_failure_log: dict[str, list[datetime]] = defaultdict(list)


# ─── Auth failure tracking ────────────────────────────────────────────────────

def record_login_failure(ip: str) -> None:
    with _lock:
        now = datetime.utcnow()
        _failure_log[ip].append(now)
        # prune entries outside window to keep memory bounded
        cutoff = now - timedelta(seconds=_WINDOW_SECONDS)
        _failure_log[ip] = [t for t in _failure_log[ip] if t >= cutoff]


def record_login_success(ip: str) -> None:
    """Successful login clears failure history for this IP."""
    with _lock:
        _failure_log.pop(ip, None)


def check_brute_force(ip: str) -> bool:
    """Return True if the IP has reached the brute-force threshold."""
    return get_failure_count(ip) >= _MAX_FAILURES


def get_failure_count(ip: str) -> int:
    with _lock:
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=_WINDOW_SECONDS)
        return len([t for t in _failure_log.get(ip, []) if t >= cutoff])


# ─── SQL injection / XSS patterns ────────────────────────────────────────────
# These are checked against URL query strings only (bodies are not scanned
# to avoid false positives on binary/JSON content).

SQL_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"(\%27)|(\')|(\-\-)|(\%23)|(#)",                          re.IGNORECASE),
    re.compile(r"((\%3D)|(=))[^\n]*((\%27)|(\')|(\-\-)|(\%3B)|(;))",     re.IGNORECASE),
    re.compile(r"\w*((\%27)|(\'))((\%6F)|o|(\%4F))((\%72)|r|(\%52))",    re.IGNORECASE),
    re.compile(r"union.{0,20}select",                                      re.IGNORECASE),
    re.compile(r"select.{0,20}from",                                       re.IGNORECASE),
    re.compile(r"insert\s+into",                                           re.IGNORECASE),
    re.compile(r"drop\s+table",                                            re.IGNORECASE),
    re.compile(r"exec(\s|\+)+(s|x)p\w+",                                  re.IGNORECASE),
    re.compile(r"<script[\s>]",                                            re.IGNORECASE),
    re.compile(r"javascript\s*:",                                          re.IGNORECASE),
    re.compile(r"on\w+\s*=",                                               re.IGNORECASE),
]
