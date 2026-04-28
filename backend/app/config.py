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
    jwt_expire_minutes: int = 120  # 2 hours (shortened from 8h for XSS-exposure resilience)
    jwt_refresh_threshold_minutes: int = 30  # re-issue token if <30 min left on active request

    # Deployment marker. When set to "production", startup guards (e.g. refuse
    # to boot with an unset JWT_SECRET) become strict. Leave unset/"dev" for
    # local development where a random secret per restart is acceptable.
    app_env: str = "dev"

    # Public self-registration toggle (POST /api/auth/register creating monitor
    # accounts). Off by default so production deployments do not expose the
    # dashboard to any visitor of the public URL; flip to true only in dev or
    # behind an admin invite workflow.
    allow_self_registration: bool = False

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

    # v3.10 — Marina-local time zone for the LED schedule. Operators enter
    # `on_time` / `off_time` in this zone via the Control Center. Default is
    # UTC so a fresh dev install behaves predictably; production .env on the
    # NUC sets this to e.g. `Europe/Zagreb`. Must be a valid IANA tz name
    # parsable by zoneinfo (Python 3.9+ stdlib).
    marina_timezone: str = "UTC"

    # Hardware monitoring thresholds — percentages except hw_temp_max (°C).
    # Change in .env and restart; no code changes needed.
    hw_cpu_warning: float = 60.0    # % CPU → Alarm 1
    hw_cpu_critical: float = 80.0   # % CPU → Alarm 2 + auto nice()
    hw_mem_warning: float = 60.0    # % RAM → Alarm 1
    hw_mem_critical: float = 80.0   # % RAM → Alarm 2 + gc.collect()
    hw_disk_warning: float = 60.0   # % disk → Alarm 1 (display only)
    hw_disk_critical: float = 80.0  # % disk → Alarm 2 (display only)
    hw_temp_max: float = 90.0       # maximum safe CPU temperature (°C)
    hw_temp_warning_pct: float = 60.0   # 60% of 90°C = 54°C → Alarm 1
    hw_temp_critical_pct: float = 80.0  # 80% of 90°C = 72°C → Alarm 2 + RTSP suspend

    # Computer vision — set USE_ML_MODELS=true in .env to enable OpenVINO inference.
    # Default is false: uses fast Laplacian+histogram fallback (works on all hardware).
    # On Intel Atom x7425E, OpenVINO inference takes ~500-2000ms per click — acceptable
    # for on-demand use. Enable after running setup_openvino_models.py and measuring
    # latency via the logged "inference_ms" values.
    use_ml_models: bool = False

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
# In production (APP_ENV=production) we refuse to start with an unset or short
# secret — a per-restart random key would silently invalidate every session
# whenever systemd restarts the backend, and short keys are trivially
# brute-forceable. In dev we accept whatever is provided; if it is missing we
# auto-generate so local runs keep working.
_MIN_SECRET_LEN = 32
_is_prod = settings.app_env.lower() == "production"
if settings.jwt_secret is None or len(settings.jwt_secret) < _MIN_SECRET_LEN:
    if _is_prod:
        raise RuntimeError(
            f"JWT_SECRET must be set to a value of at least {_MIN_SECRET_LEN} characters "
            f"when APP_ENV=production. Generate one with `python -c \"import secrets; "
            f"print(secrets.token_hex(32))\"` and write it to backend/.env."
        )
    if settings.jwt_secret is None:
        settings.jwt_secret = secrets.token_hex(32)
        _config_logger.critical(
            "SECURITY WARNING: JWT_SECRET is not set. A random secret was generated — "
            "all sessions will be invalidated on every restart. Set JWT_SECRET in your .env file."
        )
    else:
        _config_logger.warning(
            "JWT_SECRET is shorter than %d chars — tolerated in dev, REJECTED in production. "
            "Set a longer secret (e.g. secrets.token_hex(32)) before enabling APP_ENV=production.",
            _MIN_SECRET_LEN,
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
