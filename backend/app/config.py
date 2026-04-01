import logging
import secrets
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

_config_logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    database_url: str = "sqlite:///./pedestal.db"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # CORS — comma-separated list of allowed origins
    allowed_origins: str = "http://localhost:5173"

    # JWT — must be set via JWT_SECRET env var in production
    jwt_secret: Optional[str] = None
    jwt_expire_minutes: int = 480  # 8 hours

    # OTP
    otp_expire_minutes: int = 10

    # SMTP (leave smtp_host empty to use console fallback in dev)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_tls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    # Pending session / socket approval timeout (seconds)
    pending_timeout_seconds: int = 15

    # Default admin credentials for first-run seeding — override via env vars
    default_admin_email: str = "admin@iot-dashboard.local"
    default_admin_password: Optional[str] = None

    # Company / branding — used in PDFs (contracts, invoices)
    company_name: str = ""
    company_address: str = ""
    company_phone: str = ""
    company_email: str = ""
    company_portal_name: str = "IoT Portal"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

# ── JWT secret resolution ─────────────────────────────────────────────────────
if settings.jwt_secret is None:
    settings.jwt_secret = secrets.token_hex(32)
    _config_logger.critical(
        "SECURITY WARNING: JWT_SECRET is not set. A random secret was generated — "
        "all sessions will be invalidated on every restart. "
        "Set JWT_SECRET in your .env file."
    )

# ── Admin password check ──────────────────────────────────────────────────────
if settings.default_admin_password is None:
    _config_logger.warning(
        "DEFAULT_ADMIN_PASSWORD is not set. Default admin user will NOT be seeded on first run. "
        "Set DEFAULT_ADMIN_PASSWORD in your .env file."
    )

# ── SMTP from address fallback ────────────────────────────────────────────────
if not settings.smtp_from:
    settings.smtp_from = f"noreply@{settings.default_admin_email.split('@')[-1]}"
