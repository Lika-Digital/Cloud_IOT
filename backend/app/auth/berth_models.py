"""ORM models for marina berths and berth reservations."""
from datetime import datetime, date
from sqlalchemy import String, Integer, Float, Text, DateTime, Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .user_database import UserBase



class Berth(UserBase):
    __tablename__ = "berths"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Optional reference to a pedestal (plain int, no FK — pedestals live in pedestal.db)
    pedestal_id: Mapped[int] = mapped_column(Integer, nullable=True)
    # "transit" | "yearly"
    berth_type: Mapped[str] = mapped_column(String(20), default="transit")
    # "free" | "occupied" | "reserved"
    status: Mapped[str] = mapped_column(String(20), default="free")
    # Latest status determined by ML analyzer (never "reserved")
    detected_status: Mapped[str] = mapped_column(String(20), default="free")
    # Filename of the video stream (relative to frontend/src/assets/)
    video_source: Mapped[str] = mapped_column(String(255), nullable=True)
    # Filename of the contracted-ship reference image (relative to frontend/src/assets/)
    reference_image: Mapped[str] = mapped_column(String(255), nullable=True)
    # Filename of the empty-berth background snapshot (relative to backend/backgrounds/)
    # Used by the ML worker pre-screening step to skip RT-DETR on unchanged scenes.
    background_image: Mapped[str] = mapped_column(String(255), nullable=True)
    # RT-DETR minimum detection confidence to declare a vessel present
    detect_conf_threshold: Mapped[float] = mapped_column(Float, default=0.30)
    # DINOv2 cosine-similarity threshold to declare a ship match
    match_threshold: Mapped[float] = mapped_column(Float, default=0.50)
    # Zone-based detection: restrict vessel detection to a rectangular ROI
    # expressed as fractions of frame dimensions (0.0 – 1.0)
    use_detection_zone: Mapped[int] = mapped_column(Integer, default=1)   # bool as int
    zone_x1: Mapped[float] = mapped_column(Float, default=0.20)
    zone_y1: Mapped[float] = mapped_column(Float, default=0.20)
    zone_x2: Mapped[float] = mapped_column(Float, default=0.80)
    zone_y2: Mapped[float] = mapped_column(Float, default=0.80)
    # Last ML output fields (persisted for frontend query without waiting for next cycle)
    occupied_bit: Mapped[int] = mapped_column(Integer, default=0)
    match_ok_bit: Mapped[int] = mapped_column(Integer, default=0)
    state_code: Mapped[int] = mapped_column(Integer, default=0)   # 0=FREE 1=OK 2=WRONG
    alarm: Mapped[int] = mapped_column(Integer, default=0)
    match_score: Mapped[float] = mapped_column(Float, nullable=True)
    analysis_error: Mapped[str] = mapped_column(Text, nullable=True)
    last_analyzed: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Re-ID embedding path and update timestamp (Section 7)
    sample_embedding_path: Mapped[str] = mapped_column(String(500), nullable=True)
    sample_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # User-assigned berth number (e.g. 1, 2, 3) — distinct from DB primary key
    berth_number: Mapped[int] = mapped_column(Integer, nullable=True)


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
