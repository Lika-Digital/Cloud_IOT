from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, UniqueConstraint
from ..database import Base


class PilotAssignment(Base):
    """
    Pilot mode: maps a customer username to an allowed pedestal + socket.
    pedestal_id is a plain integer (no FK) so assignments survive the
    pedestal-table wipe that happens on every application restart.
    One assignment per pedestal/socket combination.
    """
    __tablename__ = "pilot_assignments"

    id          = Column(Integer, primary_key=True, index=True)
    username    = Column(String(120), nullable=False)   # matches Customer.name
    pedestal_id = Column(Integer, nullable=False)
    socket_id   = Column(Integer, nullable=False)       # 1–4
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("pedestal_id", "socket_id", name="uq_pilot_assignment_socket"),
    )
