"""TC-UIR-04 — no screen shows watts derived from `powerKw` (D19).

The websocket `power_reading.watts` is `powerKw * 1000` from the `opta/events` payload
(`mqtt_handlers._handle_event_telemetry_update`). `powerKw` was measured up to 100x too high and
that message carries no voltage or current, so it cannot be turned into amps. The admin profile
showed it anyway, as "Power ... W" (PedestalView), until 2026-10-14. Current in amps comes from
the meter telemetry (`socketLoadStates[..].current_amps`) and is shown beside it already.

THE RULE: no .tsx file reads `.watts`. The store and the websocket hook may still carry the field
(.ts files): the backend still sends it, and a stored value nobody renders is harmless.

FAILS on the code before this change: PedestalView.tsx, plus SocketCard.tsx and
ActiveSessions.tsx (both imported nowhere, deleted in the same commit).
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
WATTS = re.compile(r"\.watts\b")


def test_tc_uir_04_no_tsx_renders_powerkw_watts():
    offenders = [
        f"{p.relative_to(SRC).as_posix()}:{n}: {line.strip()}"
        for p in sorted(SRC.rglob("*.tsx"))
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if WATTS.search(line)
    ]
    assert not offenders, (
        "These lines display watts computed from powerKw (D19) — show the meter's current_amps "
        "instead:\n  " + "\n  ".join(offenders))


def test_tc_uir_04b_the_scan_sees_tsx_files():
    """A scan over an empty tree passes vacuously; make sure it is looking at the real one."""
    assert (SRC / "components" / "pedestal" / "PedestalView.tsx").is_file()
    assert sum(1 for _ in SRC.rglob("*.tsx")) > 20
