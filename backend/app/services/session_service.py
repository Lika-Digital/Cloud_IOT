import logging
from datetime import datetime
from sqlalchemy.orm import Session as DBSession
from ..models.session import Session
from ..models.sensor_reading import SensorReading

logger = logging.getLogger(__name__)


class SessionService:
    def create_pending(
        self,
        db: DBSession,
        pedestal_id: int,
        socket_id: int | None,
        session_type: str,
    ) -> Session:
        session = Session(
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            type=session_type,
            status="pending",
            started_at=datetime.utcnow(),
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        logger.info(f"Created pending session {session.id} for pedestal {pedestal_id} socket {socket_id}")
        return session

    def activate(self, db: DBSession, session: Session) -> Session:
        session.status = "active"
        db.commit()
        db.refresh(session)
        return session

    def deny(self, db: DBSession, session: Session) -> Session:
        session.status = "denied"
        session.ended_at = datetime.utcnow()
        db.commit()
        db.refresh(session)
        return session

    def complete(self, db: DBSession, session: Session) -> Session:
        session.status = "completed"
        session.ended_at = datetime.utcnow()

        # Calculate totals from sensor readings
        readings = (
            db.query(SensorReading)
            .filter(SensorReading.session_id == session.id)
            .all()
        )
        if session.type == "electricity":
            kwh_readings = [r.value for r in readings if r.type == "kwh_total"]
            if kwh_readings:
                session.energy_kwh = max(kwh_readings) - min(kwh_readings)
        elif session.type == "water":
            liter_readings = [r.value for r in readings if r.type == "total_liters"]
            if liter_readings:
                session.water_liters = max(liter_readings) - min(liter_readings)

        db.commit()
        db.refresh(session)
        return session

    def get_active_for_socket(
        self, db: DBSession, pedestal_id: int, socket_id: int | None
    ) -> Session | None:
        return (
            db.query(Session)
            .filter(
                Session.pedestal_id == pedestal_id,
                Session.socket_id == socket_id,
                Session.status.in_(["pending", "active"]),
            )
            .first()
        )

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
        db.add(reading)
        db.commit()
        db.refresh(reading)
        return reading


session_service = SessionService()
