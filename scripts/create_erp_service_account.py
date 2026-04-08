"""
create_erp_service_account.py — Create an api_client service account for ERP-IOT.

Usage:
    python scripts/create_erp_service_account.py --email erp@service.local --password SecretPass1!

The script is idempotent: if the user already exists, it prints a message and exits cleanly.
Password is hashed using the same PBKDF2-HMAC-SHA256 method as the rest of the auth system.
"""
import argparse
import sys
from pathlib import Path

# Ensure backend app is importable
BACKEND_DIR = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.auth.user_database import UserSessionLocal, init_user_db
from app.auth.models import User
from app.auth.password import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an ERP-IOT api_client service account")
    parser.add_argument("--email", required=True, help="Service account email address")
    parser.add_argument("--password", required=True, help="Service account password")
    args = parser.parse_args()

    # Ensure DB and tables exist
    init_user_db()

    db = UserSessionLocal()
    try:
        existing = db.query(User).filter(User.email == args.email).first()
        if existing:
            print(f"[INFO] User '{args.email}' already exists (role={existing.role}, active={existing.is_active}).")
            print("       No changes made. Exiting cleanly.")
            return

        user = User(
            email=args.email,
            password_hash=hash_password(args.password),
            role="api_client",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"[OK] Service account created: {user.email} (id={user.id}, role=api_client)")
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] Failed to create service account: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
