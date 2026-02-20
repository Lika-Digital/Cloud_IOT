from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base


class Pedestal(Base):
    __tablename__ = "pedestals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=True)
    ip_address: Mapped[str] = mapped_column(String(50), nullable=True)
    data_mode: Mapped[str] = mapped_column(String(20), default="synthetic")

    sessions: Mapped[list["Session"]] = relationship(  # noqa: F821
        "Session", back_populates="pedestal"
    )
    sensor_readings: Mapped[list["SensorReading"]] = relationship(  # noqa: F821
        "SensorReading", back_populates="pedestal"
    )
