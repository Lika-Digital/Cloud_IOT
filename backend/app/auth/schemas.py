from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class LoginRequest(BaseModel):
    # Use str (not EmailStr) — email-validator rejects .local TLD used by default admin account
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class VerifyOtpRequest(BaseModel):
    email: str = Field(..., max_length=254)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: str = Field("monitor", pattern=r"^(admin|monitor)$")


class UserResponse(BaseModel):
    id: int
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class RegisterRequest(BaseModel):
    # Use str (not EmailStr) for broad compatibility
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=8, max_length=128)


class UserPatch(BaseModel):
    role: Optional[str] = Field(None, pattern=r"^(admin|monitor)$")
    is_active: Optional[bool] = None


class SmtpConfigUpdate(BaseModel):
    host: str = ""
    port: int = 587
    tls: bool = True
    username: str = ""
    password: str = ""
    from_email: str = ""
