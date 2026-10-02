"""v3.44 — berth → socket assignment writes.

Kept out of the router so every path that writes an assignment passes the same validation. A
route-level check protects the routes that existed when it was written; this protects the
invariant.
"""
import logging

from sqlalchemy.orm import Session as DBSession

from ..models.berth_assignment import BerthAssignment
from ..services.nfc_service import VALID_OUTLETS, OUTLET_SOCKET
from ..time_utils import iso_z

logger = logging.getLogger(__name__)

# 1..4 — derived from the outlet vocabulary rather than restated, so there is one list.
VALID_SOCKET_IDS = tuple(int(n[1:]) for n in VALID_OUTLETS[OUTLET_SOCKET])


class BerthAssignmentError(ValueError):
    """A mapping that would misattribute consumption. Refused, never corrected."""


def replace_berth_assignments(db: DBSession, pedestal_id: int, items: list,
                              *, assigned_by: str) -> list[dict]:
    """Replace the whole mapping for one pedestal.

    Validated as a SET before anything is written, because the invariant is a property of the
    set: "no socket serves two berths" cannot be checked one row at a time. A per-row write
    loop would pass every individual check and still leave two berths on one socket halfway
    through.
    """
    if not (assigned_by or "").strip():
        raise BerthAssignmentError(
            "assigned_by is required — re-pointing a berth decides which customer's "
            "consumption lands where, and every path that does it must say who did it"
        )

    cleaned: list[dict] = []
    seen_berths: set[int] = set()
    seen_sockets: set[int] = set()

    for raw in items:
        if not isinstance(raw, dict):
            raise BerthAssignmentError(f"each assignment must be an object, got {type(raw).__name__}")

        berth_id = raw.get("berth_id")
        if not isinstance(berth_id, int):
            raise BerthAssignmentError(f"berth_id must be an integer, got {berth_id!r}")
        if berth_id in seen_berths:
            raise BerthAssignmentError(
                f"berth {berth_id} appears twice in the same request"
            )
        seen_berths.add(berth_id)

        socket_id = raw.get("socket_id")
        if socket_id is not None:
            if not isinstance(socket_id, int) or socket_id not in VALID_SOCKET_IDS:
                raise BerthAssignmentError(
                    f"socket_id must be one of {list(VALID_SOCKET_IDS)} or null, "
                    f"got {socket_id!r}"
                )
            if socket_id in seen_sockets:
                # The defect this prevents: one customer's kWh appearing against two berths,
                # with no way to tell which one drew it.
                raise BerthAssignmentError(
                    f"socket Q{socket_id} is assigned to two berths in the same request — "
                    f"a socket serves exactly one berth"
                )
            seen_sockets.add(socket_id)

        # NOTE: no valve_id. Water serves a maximum of two users at a time via two valves and
        # the valves are not piped to specific berths, so water has no berth to belong to.
        # See backend/app/models/berth_assignment.py.
        cleaned.append({"berth_id": berth_id, "socket_id": socket_id})

    # Replace wholesale, inside one transaction.
    db.query(BerthAssignment).filter(
        BerthAssignment.pedestal_id == pedestal_id
    ).delete(synchronize_session=False)

    saved: list[dict] = []
    for c in cleaned:
        row = BerthAssignment(
            berth_id=c["berth_id"],
            pedestal_id=pedestal_id,
            socket_id=c["socket_id"],
            assigned_by=assigned_by,
        )
        db.add(row)
        saved.append(c)
    db.commit()

    for c in saved:
        logger.info("[Marina] berth=%s -> pedestal=%s socket=%s by %s",
                    c["berth_id"], pedestal_id, c["socket_id"], assigned_by)
    return saved
