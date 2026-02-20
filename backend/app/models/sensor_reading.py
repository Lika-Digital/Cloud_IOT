from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("sessions.id"), nullable=True)
    pedestal_id: Mapped[int] = mapped_column(Integer, ForeignKey("pedestals.id"), nullable=False)
    socket_id: Mapped[int] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # power_watts|water_lpm|kwh_total|...
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["Session"] = relationship("Session", back_populates="sensor_readings")  # noqa: F821
    pedestal: Mapped["Pedestal"] = relationship("Pedestal", back_populates="sensor_readings")  # noqa: F821
