"""Pydantic schemas for customer-facing API."""
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None
    vat_number: Optional[str] = None
    ship_name: Optional[str] = None
    ship_registration: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CustomerProfileResponse(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    vat_number: Optional[str] = None
    ship_name: Optional[str] = None
    ship_registration: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StartSessionRequest(BaseModel):
    pedestal_id: int
    type: str  # "electricity" | "water"
    socket_id: Optional[int] = None
    side: Optional[str] = None  # "left" | "right" (water)


class InvoiceResponse(BaseModel):
    id: int
    session_id: int
    customer_id: Optional[int] = None
    energy_kwh: Optional[float] = None
    water_liters: Optional[float] = None
    energy_cost_eur: Optional[float] = None
    water_cost_eur: Optional[float] = None
    total_eur: float
    paid: int
    created_at: datetime

    model_config = {"from_attributes": True}


class BillingConfigResponse(BaseModel):
    id: int
    kwh_price_eur: float
    liter_price_eur: float
    updated_at: datetime

    model_config = {"from_attributes": True}


class BillingConfigUpdate(BaseModel):
    kwh_price_eur: float
    liter_price_eur: float


class CustomerSpendingRow(BaseModel):
    customer_id: int
    customer_name: Optional[str] = None
    customer_email: str
    session_count: int
    total_kwh: float
    total_liters: float
    total_eur: float


class CustomerListRow(BaseModel):
    id: int
    email: str
    name: Optional[str] = None
    ship_name: Optional[str] = None
    active_session_id: Optional[int] = None
    active_session_type: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatMessageResponse(BaseModel):
    id: int
    customer_id: int
    message: str
    direction: str
    created_at: datetime
    read_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PedestalStatusResponse(BaseModel):
    id: int
    name: str
    location: Optional[str] = None
    occupied_sockets: list[int]
    water_occupied: bool


class SendMessageRequest(BaseModel):
    message: str


class OperatorReplyRequest(BaseModel):
    message: str
