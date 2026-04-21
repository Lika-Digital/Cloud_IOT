"""Auto-activation audit trail.

Every time an auto-activation is attempted for a socket (fires or is skipped)
one row lands here. The /api/pedestals/{id}/sockets/{id}/auto-activate-log
endpoint returns the last 20 rows for that socket so an operator can see why
auto-activation did or did not fire.

No rotation policy yet — rows accumulate. At real marina scale (≤20 pedestals
× 4 sockets × a few plug-ins per day) this is in the order of tens of rows
per day and costs nothing to keep.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from ..database import Base


class AutoActivationLog(Base):
    __tablename__ = "auto_activation_log"

    id          = Column(Integer, primary_key=True, index=True)
    pedestal_id = Column(Integer, ForeignKey("pedestals.id"), nullable=False)
    socket_id   = Column(Integer, nullable=False)
    timestamp   = Column(DateTime, default=datetime.utcnow, nullable=False)
    result      = Column(String, nullable=False)   # "success" | "skipped"
    reason      = Column(String, nullable=True)    # populated when result == "skipped"
    session_id  = Column(Integer, nullable=True)   # populated when result == "success"

    __table_args__ = (
        Index("ix_autoact_sock_time", "pedestal_id", "socket_id", "timestamp"),
    )
