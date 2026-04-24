import logging
import traceback
from datetime import datetime
from sqlalchemy.orm import Session as DBSession
from ..models.session import Session
from ..models.sensor_reading import SensorReading

logger = logging.getLogger(__name__)


def _log(category: str, source: str, msg: str, exc: Exception | None = None):
    """Fire-and-forget to error_log_service without crashing the caller."""
    try:
        from .error_log_service import log_error
        details = traceback.format_exc() if exc else None
        log_error(category, source, msg, details=details)
    except Exception:
        pass


class SessionService:
    def create_pending(
        self,
        db: DBSession,
        pedestal_id: int,
        socket_id: int | None,
        session_type: str,
        customer_id: int | None = None,
    ) -> Session:
        """Create a pending session. If a partial unique index has already
        accepted another thread's insert for the same (pedestal, socket, type)
        with status in (pending, active), return that row instead of raising —
        MQTT firmware retries must not create duplicates.
        """
        from sqlalchemy.exc import IntegrityError
        session = Session(
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            type=session_type,
            status="pending",
            started_at=datetime.utcnow(),
            customer_id=customer_id,
        )
        try:
            db.add(session)
            db.commit()
            db.refresh(session)
        except IntegrityError:
            db.rollback()
            existing = self.get_active_for_socket(db, pedestal_id, socket_id, session_type=session_type)
            if existing:
                logger.info(
                    f"create_pending: active session {existing.id} already exists for "
                    f"pedestal={pedestal_id} socket={socket_id} type={session_type}; returning it"
                )
                return existing
            _log("system", "session_service",
                 f"IntegrityError on create_pending (pedestal={pedestal_id}, socket={socket_id}) "
                 f"but no active row found — race without winner?")
            raise
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to create pending session (pedestal={pedestal_id}): {e}", e)
            raise
        logger.info(f"Created pending session {session.id} for pedestal {pedestal_id} socket {socket_id}")
        return session

    def activate(self, db: DBSession, session: Session) -> Session:
        try:
            session.status = "active"
            db.commit()
            db.refresh(session)
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to activate session {session.id}: {e}", e)
            raise
        return session

    def deny(self, db: DBSession, session: Session, reason: str | None = None) -> Session:
        try:
            session.status = "denied"
            session.ended_at = datetime.utcnow()
            if reason:
                session.deny_reason = reason
            db.commit()
            db.refresh(session)
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to deny session {session.id}: {e}", e)
            raise
        return session

    def complete(
        self,
        db: DBSession,
        session: Session,
        end_reason: str | None = None,
    ) -> Session:
        """Finalise a session.

        `end_reason` is stored machine-readable on `sessions.end_reason` when set
        (e.g. "breaker_trip"). Legacy call sites can omit it; the column stays NULL
        for the natural unplug / operator-stop paths.
        """
        session.status = "completed"
        session.ended_at = datetime.utcnow()
        if end_reason:
            session.end_reason = end_reason

        # Calculate totals from sensor readings
        readings = (
            db.query(SensorReading)
            .filter(SensorReading.session_id == session.id)
            .all()
        )
        if session.type == "electricity":
            kwh_readings = [r.value for r in readings if r.type == "kwh_total"]
            if kwh_readings:
                # Firmware sends session-cumulative energy (resets to 0 at session
                # start, rises to session total). Final value = max, which also
                # covers short sessions where only the SessionEnded reading exists.
                session.energy_kwh = max(kwh_readings)
        elif session.type == "water":
            liter_readings = [r.value for r in readings if r.type == "total_liters"]
            if liter_readings:
                session.water_liters = max(liter_readings)

        try:
            db.commit()
            db.refresh(session)
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to complete session {session.id}: {e}", e)
            raise
        return session

    def get_active_for_socket(
        self,
        db: DBSession,
        pedestal_id: int,
        socket_id: int | None,
        session_type: str | None = None,
    ) -> Session | None:
        """Find the active session for (pedestal, socket).

        `session_type` filter is used by MQTT handlers so a water session on V1
        does not accidentally collide with an electricity session carrying the
        same numeric socket_id from a legacy row.
        """
        q = (
            db.query(Session)
            .filter(
                Session.pedestal_id == pedestal_id,
                Session.socket_id == socket_id,
                Session.status.in_(["pending", "active"]),
            )
        )
        if session_type is not None:
            q = q.filter(Session.type == session_type)
        return q.first()

    def add_reading(
        self,
        db: DBSession,
        session_id: int | None,
        pedestal_id: int,
        socket_id: int | None,
        reading_type: str,
        value: float,
        unit: str,
    ) -> SensorReading:
        reading = SensorReading(
            session_id=session_id,
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            type=reading_type,
            value=value,
            unit=unit,
        )
        try:
            db.add(reading)
            db.commit()
            db.refresh(reading)
        except Exception as e:
            db.rollback()
            _log("system", "session_service", f"Failed to persist sensor reading ({reading_type}): {e}", e)
            raise
        return reading


session_service = SessionService()
