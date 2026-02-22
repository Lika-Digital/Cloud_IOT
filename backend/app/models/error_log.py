from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class ErrorLog(Base):
    """
    Stores system and hardware error events for the System Health dashboard.
    Records are automatically purged after 7 days.

    category:
        'system' — software/API/DB/infrastructure errors
        'hw'     — hardware/MQTT/sensor/pedestal errors

    level:
        'error'   — failure that needs attention
        'warning' — non-critical issue (e.g. sensor alarm, invalid payload)
        'info'    — notable event logged for audit trail
    """
    __tablename__ = "error_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    level: Mapped[str] = mapped_column(String(10), nullable=False, index=True)     # error|warning|info
    category: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # system|hw
    source: Mapped[str] = mapped_column(String(100), nullable=False)               # module/component
    message: Mapped[str] = mapped_column(String(500), nullable=False)              # short description
    details: Mapped[str] = mapped_column(Text, nullable=True)                      # traceback or JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
