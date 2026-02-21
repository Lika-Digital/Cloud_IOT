"""
Send OTP via email using smtplib (stdlib).
Falls back to console print when SMTP is not configured (dev mode).
"""
import logging
import smtplib
from email.mime.text import MIMEText
from ..config import settings

logger = logging.getLogger(__name__)


def send_otp_email(to_email: str, otp_code: str) -> None:
    subject = "Your IoT Dashboard login code"
    body = (
        f"Your one-time login code is:\n\n"
        f"    {otp_code}\n\n"
        f"This code expires in {settings.otp_expire_minutes} minutes.\n"
        f"If you did not request this, ignore this message."
    )

    if not settings.smtp_host:
        # Dev fallback — print to console
        logger.warning(
            "SMTP not configured. OTP for %s: %s", to_email, otp_code
        )
        print(f"\n{'='*50}")
        print(f"  OTP for {to_email}: {otp_code}")
        print(f"{'='*50}\n")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            if settings.smtp_tls:
                server.starttls()
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, [to_email], msg.as_string())
        logger.info("OTP email sent to %s", to_email)
    except Exception as exc:
        logger.error("Failed to send OTP email to %s: %s", to_email, exc)
        # Still print to console so dev can proceed
        print(f"\n  [EMAIL FAILED] OTP for {to_email}: {otp_code}\n")
