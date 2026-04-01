import logging
from datetime import datetime
from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger(__name__)


def log_transition(
    db: DBSession,
    session_id: int | None,
    pedestal_id: int,
    socket_id: int | None,
    action: str,
    actor_type: str,
    actor_id: str | int | None = None,
    reason: str | None = None,
) -> None:
    """Write an audit log entry for a socket/session state transition. Never raises."""
    try:
        from ..models.session_audit import SessionAuditLog
        db.add(SessionAuditLog(
            session_id=session_id,
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            action=action,
            actor_type=actor_type,
            actor_id=str(actor_id) if actor_id is not None else None,
            reason=reason,
            timestamp=datetime.utcnow(),
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("Audit log write failed (session=%s, action=%s): %s", session_id, action, e)
