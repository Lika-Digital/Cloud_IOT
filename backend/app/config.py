import logging
from pydantic_settings import BaseSettings, SettingsConfigDict

_config_logger = logging.getLogger(__name__)

_DEFAULT_JWT_SECRET = "change-me-in-production-use-a-long-random-string"


class Settings(BaseSettings):
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1883
    database_url: str = "sqlite:///./pedestal.db"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # CORS — comma-separated list of allowed origins
    allowed_origins: str = "http://localhost:5173"

    # JWT
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_expire_minutes: int = 480  # 8 hours

    # OTP
    otp_expire_minutes: int = 10

    # SMTP (leave smtp_host empty to use console fallback in dev)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_tls: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@iot-dashboard.local"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

if settings.jwt_secret == _DEFAULT_JWT_SECRET:
    _config_logger.critical(
        "SECURITY WARNING: jwt_secret is set to the default value. "
        "Set JWT_SECRET in your .env file before deploying to production!"
    )
