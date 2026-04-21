from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from ..database import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pedestal_id: Mapped[int] = mapped_column(Integer, ForeignKey("pedestals.id"), nullable=False)
    # socket_id is 1-4 for electricity sockets and 1-2 for water valves (V1, V2).
    # Legacy completed rows may still have NULL for water; SQLite treats NULL as
    # distinct under UNIQUE so the partial index below does not conflict.
    socket_id: Mapped[int] = mapped_column(Integer, nullable=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)   # "electricity" | "water"
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|active|completed|denied
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    energy_kwh: Mapped[float] = mapped_column(Float, nullable=True)
    water_liters: Mapped[float] = mapped_column(Float, nullable=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=True)
    deny_reason: Mapped[str] = mapped_column(String(500), nullable=True)
    # v3.6 — set when an auto-activated (customer_id=NULL) session is later
    # claimed by a customer via QR scan. Lets us distinguish sessions started
    # from the mobile app (owner_claimed_at=NULL, customer_id=customer.id)
    # from sessions claimed after-the-fact (both set). Does not replace
    # customer_id — that remains the sole FK to the Customer table.
    owner_claimed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    pedestal: Mapped["Pedestal"] = relationship("Pedestal", back_populates="sessions")  # noqa: F821
    sensor_readings: Mapped[list["SensorReading"]] = relationship(  # noqa: F821
        "SensorReading", back_populates="session"
    )

    __table_args__ = (
        # One active (pending|active) session per (pedestal, socket, type).
        # Firmware retries on ack loss used to duplicate; this index makes
        # duplicate INSERT fail at the DB layer so create_pending can recover.
        Index(
            "ux_session_one_active_per_socket",
            "pedestal_id", "socket_id", "type",
            unique=True,
            sqlite_where=text("status IN ('pending', 'active')"),
        ),
    )
