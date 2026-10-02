"""v3.44 — which electricity socket serves which berth.

One row per berth. Lives in `pedestal.db` beside sockets, valves and `energy_intervals`,
so every join the marina dashboard needs stays inside one database. `berth_id` crosses to
`users.db` as a plain int with no FK — the same compromise `Berth.pedestal_id` already makes,
so this adds no new kind of problem.

THERE IS NO `valve_id` HERE, AND THAT IS THE POINT
--------------------------------------------------
An earlier draft gave each berth a `valve_id` with sharing allowed. The Krk layout settled
2026-10-01 says something different: **one pedestal covers 4 berths for electricity, one
socket each, and water serves a maximum of 2 users at a time via the 2 valves.**

That second half is a CAPACITY statement, not a mapping. The valves are not piped to specific
berths — a customer walks to whichever valve is free and scans the tag on it. So water has no
berth to belong to, and modelling one would invent a relationship the plumbing does not have:
the dashboard would show "Water OFF" on a berth row whose occupant may be using the valve at
the other end of the cabinet, or none at all.

Water is therefore a **cabinet-level** facility (two outlets, each showing whoever's session is
on it) and attribution is by scanned tag, exactly as for electricity. See
`docs/architecture.md §2` — monitoring axis and billing axis are different, and this is the
clearest case of it.

WHY `assigned_by` IS NOT NULLABLE
---------------------------------
Re-pointing a berth to a different socket decides which customer's consumption lands where.
The service layer refuses a row without an actor, for the same reason `provision_tag` does: a
caller with no actor has a bug, and a default of "(unknown)" hides it.
"""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, UniqueConstraint,
)

from ..database import Base


class BerthAssignment(Base):
    __tablename__ = "berth_assignments"

    id          = Column(Integer, primary_key=True, index=True)

    # Berth.id from users.db. Plain int, no FK — cross-database.
    berth_id    = Column(Integer, nullable=False, index=True)
    pedestal_id = Column(Integer, ForeignKey("pedestals.id"), nullable=False, index=True)

    # 1..4. Nullable because a berth with no power is a real installation and the UI must
    # render it rather than refuse to.
    socket_id   = Column(Integer, nullable=True)

    assigned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    assigned_by = Column(String, nullable=False)

    __table_args__ = (
        # A socket serves at most one berth. Enforced here as well as in the wizard, because
        # two berths sharing a socket would make a single customer's kWh appear against two
        # berths and there would be no way to tell which one drew it.
        UniqueConstraint("pedestal_id", "socket_id", name="uq_berth_assignment_socket"),
        # A berth has at most one assignment.
        UniqueConstraint("berth_id", name="uq_berth_assignment_berth"),
    )
