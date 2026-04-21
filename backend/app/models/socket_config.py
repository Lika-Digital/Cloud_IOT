"""Per-socket configuration.

Holds the `auto_activate` flag for each (pedestal_id, socket_id) pair so an
operator can opt individual sockets into the auto-activation flow introduced
in v3.5. Water valves are intentionally not represented — the feature is
electricity-only.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint
from ..database import Base


class SocketConfig(Base):
    __tablename__ = "socket_configs"

    id            = Column(Integer, primary_key=True, index=True)
    pedestal_id   = Column(Integer, ForeignKey("pedestals.id"), nullable=False, index=True)
    socket_id     = Column(Integer, nullable=False)   # 1–4
    auto_activate = Column(Boolean, nullable=False, default=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("pedestal_id", "socket_id", name="uq_socket_config"),
    )
