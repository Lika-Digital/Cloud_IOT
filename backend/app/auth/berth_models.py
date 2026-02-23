"""ORM models for marina berths and berth reservations."""
from datetime import datetime, date
from sqlalchemy import String, Integer, Text, DateTime, Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .user_database import UserBase


class Berth(UserBase):
    __tablename__ = "berths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Optional reference to a pedestal (plain int, no FK since it lives in pedestal.db)
    pedestal_id: Mapped[int] = mapped_column(Integer, nullable=True)
    # "free" | "occupied" | "reserved"
    status: Mapped[str] = mapped_column(String(20), default="free")
    # Latest status reported by the analyzer
    detected_status: Mapped[str] = mapped_column(String(20), default="free")
    # Filename of the video source used by the analyzer (relative to frontend/src/assets/)
    video_source: Mapped[str] = mapped_column(String(255), nullable=True)
    last_analyzed: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BerthReservation(UserBase):
    __tablename__ = "berth_reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    berth_id: Mapped[int] = mapped_column(Integer, ForeignKey("berths.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    check_in_date: Mapped[date] = mapped_column(Date, nullable=False)
    check_out_date: Mapped[date] = mapped_column(Date, nullable=False)
    # "confirmed" | "cancelled"
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
