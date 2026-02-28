"""
Send OTP / notification emails using smtplib (stdlib).
Runtime SMTP config is read from the smtp_config DB table (set via admin UI).
Falls back to .env settings, then console print when nothing is configured.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from ..config import settings

logger = logging.getLogger(__name__)


def _get_smtp_config() -> dict | None:
    """
    Load effective SMTP config. Priority:
    1. smtp_config table in users.db (admin UI settings)
    2. .env settings (SMTP_HOST / SMTP_PORT / …)
    Returns None if SMTP is not configured anywhere.
    """
    try:
        from .user_database import UserSessionLocal
        from .models import SmtpConfig
        db = UserSessionLocal()
        try:
            cfg = db.get(SmtpConfig, 1)
            if cfg and cfg.host:
                return {
                    "host": cfg.host,
                    "port": cfg.port,
                    "tls": bool(cfg.tls),
                    "user": cfg.username,
                    "password": cfg.password,
                    "from": cfg.from_email or settings.smtp_from,
                }
        finally:
            db.close()
    except Exception:
        pass

    # Fallback: .env settings
    if settings.smtp_host:
        return {
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "tls": settings.smtp_tls,
            "user": settings.smtp_user,
            "password": settings.smtp_password,
            "from": settings.smtp_from,
        }
    return None


def _send_via_smtp(cfg: dict, to_email: str, subject: str, body: str) -> None:
    """Send a single email using the provided SMTP config. Raises on failure."""
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = to_email

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as server:
        if cfg["tls"]:
            server.starttls()
        if cfg["user"] and cfg["password"]:
            server.login(cfg["user"], cfg["password"])
        server.sendmail(cfg["from"], [to_email], msg.as_string())


def send_otp_email(to_email: str, otp_code: str) -> None:
    subject = "Your IoT Dashboard login code"
    body = (
        f"Your one-time login code is:\n\n"
        f"    {otp_code}\n\n"
        f"This code expires in {settings.otp_expire_minutes} minutes.\n"
        f"If you did not request this, ignore this message."
    )

    cfg = _get_smtp_config()
    if not cfg:
        logger.warning("SMTP not configured. OTP for %s: %s", to_email, otp_code)
        print(f"\n{'='*50}")
        print(f"  OTP for {to_email}: {otp_code}")
        print(f"{'='*50}\n")
        return

    try:
        _send_via_smtp(cfg, to_email, subject, body)
        logger.info("OTP email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send OTP email to %s: %s", to_email, exc)
        # Still print to console so admin can proceed
        print(f"\n  [EMAIL FAILED] OTP for {to_email}: {otp_code}\n")


def send_test_email(to_email: str) -> None:
    """Send a test email. Raises on any SMTP failure (used by admin test endpoint)."""
    cfg = _get_smtp_config()
    if not cfg:
        raise ValueError("SMTP is not configured. Set SMTP settings in the admin panel first.")

    subject = "IoT Dashboard — SMTP test"
    body = (
        "This is a test email from the IoT Dashboard admin panel.\n\n"
        "If you received this, your SMTP configuration is working correctly."
    )
    _send_via_smtp(cfg, to_email, subject, body)
    logger.info("Test email sent to %s", to_email)


def smtp_is_configured() -> bool:
    """Return True if SMTP is configured (DB or .env)."""
    return _get_smtp_config() is not None
