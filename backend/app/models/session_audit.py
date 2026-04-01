from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime
from ..database import Base


class SessionAuditLog(Base):
    __tablename__ = "session_audit_log"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    session_id  = Column(Integer, nullable=True)   # null for socket-level events (no session yet)
    pedestal_id = Column(Integer, nullable=False)
    socket_id   = Column(Integer, nullable=True)
    action      = Column(String(50),  nullable=False)
    actor_type  = Column(String(20),  nullable=False)  # "customer" | "operator" | "system"
    actor_id    = Column(String(50),  nullable=True)
    reason      = Column(String(500), nullable=True)
    timestamp   = Column(DateTime, default=datetime.utcnow)
