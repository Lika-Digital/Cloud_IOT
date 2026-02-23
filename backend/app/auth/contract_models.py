"""ORM models for contracts, customer contracts, and service orders."""
from datetime import datetime
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .user_database import UserBase


class ContractTemplate(UserBase):
    __tablename__ = "contract_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    validity_days: Mapped[int] = mapped_column(Integer, default=365)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_register: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CustomerContract(UserBase):
    __tablename__ = "customer_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("contract_templates.id"), nullable=False)
    signature_data: Mapped[str] = mapped_column(Text, nullable=True)  # base64 PNG
    signed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    valid_until: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")  # 'active' | 'expired'


class ServiceOrder(UserBase):
    __tablename__ = "service_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    service_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # crane | engine_check | hull_clean | diver | battery_check | electrical_check
    notes: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
