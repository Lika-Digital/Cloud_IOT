"""Pydantic schemas for customer-facing API."""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: Optional[str] = Field(None, max_length=120)
    vat_number: Optional[str] = Field(None, max_length=40)
    ship_name: Optional[str] = Field(None, max_length=120)
    ship_registration: Optional[str] = Field(None, max_length=60)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


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
    kwh_price_eur: float = Field(..., ge=0.0, le=9999.0)
    liter_price_eur: float = Field(..., ge=0.0, le=9999.0)


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
    assigned_socket_id: Optional[int] = None  # set when customer has a pilot assignment


class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class OperatorReplyRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class SessionDetailRow(BaseModel):
    customer_id: int
    customer_name: Optional[str] = None
    customer_email: str
    session_id: int
    session_type: str
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    energy_kwh: Optional[float] = None
    water_liters: Optional[float] = None
    total_eur: float
    paid: bool
