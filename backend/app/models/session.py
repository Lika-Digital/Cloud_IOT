from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pedestal_id: Mapped[int] = mapped_column(Integer, ForeignKey("pedestals.id"), nullable=False)
    socket_id: Mapped[int] = mapped_column(Integer, nullable=True)  # null = water
    type: Mapped[str] = mapped_column(String(20), nullable=False)   # "electricity" | "water"
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|active|completed|denied
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    energy_kwh: Mapped[float] = mapped_column(Float, nullable=True)
    water_liters: Mapped[float] = mapped_column(Float, nullable=True)

    pedestal: Mapped["Pedestal"] = relationship("Pedestal", back_populates="sessions")  # noqa: F821
    sensor_readings: Mapped[list["SensorReading"]] = relationship(  # noqa: F821
        "SensorReading", back_populates="session"
    )
