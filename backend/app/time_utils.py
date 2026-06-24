"""UTC timestamp serialization helpers.

The app stores naive UTC datetimes (``datetime.utcnow()``). Emitting them to
clients without a timezone designator makes browsers' ``new Date()`` parse them
as LOCAL time, so every displayed timestamp was off by the viewer's UTC offset
(e.g. 16:00 UTC shown as 16:00 instead of 18:00 CEST). These helpers append an
explicit ``Z`` so clients convert UTC→local correctly. Use for datetimes only —
never for date-only values (``date.isoformat()`` → "YYYY-MM-DD").
"""
from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    """Current UTC time as an explicit-UTC ISO 8601 string (…Z)."""
    return datetime.utcnow().isoformat() + "Z"


def iso_z(dt: datetime | None) -> str | None:
    """Serialize a datetime as explicit-UTC ISO 8601 (…Z); None passes through.

    Naive datetimes are assumed to be UTC (the storage convention). Aware
    datetimes are converted to UTC first.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat() + "Z"
