from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from ..database import Base


class ActiveAlarm(Base):
    """
    Stateful alarm records. An alarm is 'triggered' until an operator
    acknowledges it.

    alarm_type:
        'fire'                 — customer-triggered via mobile
        'temperature'          — sensor auto (>50°C)
        'moisture'             — sensor auto (>90%)
        'unauthorized_entry'   — customer-triggered via mobile
        'comm_loss'            — watchdog: no heartbeat for 60s
        'operational_failure'  — diagnostics: sensor check failed
        'security'             — brute-force / intrusion detection

    source:
        'sensor_auto'      — raised automatically by MQTT/watchdog
        'customer_mobile'  — raised by a customer via API

    status:
        'triggered' | 'acknowledged'
    """
    __tablename__ = "active_alarms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    alarm_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    pedestal_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="triggered", index=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    acknowledged_by: Mapped[str] = mapped_column(String(255), nullable=True)
