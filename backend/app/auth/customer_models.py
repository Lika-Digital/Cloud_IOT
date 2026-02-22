"""ORM models for customer-facing features: Customer, BillingConfig, Invoice, ChatMessage."""
from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from .user_database import UserBase


class Customer(UserBase):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=True)
    vat_number: Mapped[str] = mapped_column(String(50), nullable=True)
    ship_name: Mapped[str] = mapped_column(String(255), nullable=True)
    ship_registration: Mapped[str] = mapped_column(String(100), nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BillingConfig(UserBase):
    """Single-row table (id always 1) — billing price configuration."""
    __tablename__ = "billing_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    kwh_price_eur: Mapped[float] = mapped_column(Float, default=0.30)
    liter_price_eur: Mapped[float] = mapped_column(Float, default=0.015)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Invoice(UserBase):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    energy_kwh: Mapped[float] = mapped_column(Float, nullable=True)
    water_liters: Mapped[float] = mapped_column(Float, nullable=True)
    energy_cost_eur: Mapped[float] = mapped_column(Float, nullable=True)
    water_cost_eur: Mapped[float] = mapped_column(Float, nullable=True)
    total_eur: Mapped[float] = mapped_column(Float, default=0.0)
    paid: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ChatMessage(UserBase):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)  # 'from_customer' | 'from_operator'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    read_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
