from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class LoginRequest(BaseModel):
    # Use str (not EmailStr) — email-validator rejects .local TLD used by default admin account
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    # api_client = ERP service account (external API access; no operator login/2FA)
    role: str = Field("monitor", pattern=r"^(admin|monitor_control|monitor|api_client)$")


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
    role: Optional[str] = Field(None, pattern=r"^(admin|monitor_control|monitor)$")
    is_active: Optional[bool] = None


class SmtpConfigUpdate(BaseModel):
    host: str = ""
    port: int = 587
    tls: bool = True
    username: str = ""
    password: str = ""
    from_email: str = ""


# ── v3.19 — TOTP 2FA ──────────────────────────────────────────────────────────

class LoginResponse(BaseModel):
    """v3.33 — returned by /login when credentials are valid. 2FA is mandatory
    (no JWT here). The caller then, in order: changes the password if required,
    then either enrolls TOTP (first time) or enters the authenticator code.
    Email OTP was removed — TOTP is the only second factor."""
    partial_token: str
    must_change_password: bool = False
    totp_enabled: bool = False


class FirstPasswordRequest(BaseModel):
    """Set a new password during first-login, authorized by the partial token."""
    partial_token: str = Field(..., max_length=4096)
    new_password: str = Field(..., min_length=8, max_length=128)


class PartialTokenRequest(BaseModel):
    """Body for /totp/enroll — partial token only (returns a fresh QR/secret)."""
    partial_token: str = Field(..., max_length=4096)


class TotpSetupResponse(BaseModel):
    qr_code: str                    # base64 PNG (no data: prefix)
    secret: str                     # plain secret for manual entry
    provisioning_uri: str
    warning: str = "Calling setup again invalidates the previous QR code and secret."


class TotpCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TotpDisableRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class TotpStatusResponse(BaseModel):
    totp_enabled: bool
    totp_verified_at: Optional[datetime] = None


class PartialTokenCodeRequest(BaseModel):
    """Body for /totp/login and /totp/enroll-verify — partial token + 6-digit code."""
    partial_token: str = Field(..., max_length=4096)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
