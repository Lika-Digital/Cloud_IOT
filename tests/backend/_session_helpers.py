"""Shared helpers for test cleanup of sessions.

v3.6 disabled the customer-side stop endpoint (mobile monitoring-only model),
which used to be the quick way to tidy up between tests. These helpers let
test files reset session state via direct DB writes without going through
the admin stop endpoint (which requires an extra `auth_headers` fixture and
a mocked MQTT publish).
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_TEST_DB = "sqlite:///./tests/test_pedestal.db"


def complete_session(session_id: int) -> None:
    """Mark `session_id` as completed directly in the test DB."""
    engine = create_engine(_TEST_DB, connect_args={"check_same_thread": False})
    S = sessionmaker(bind=engine)
    db = S()
    try:
        from app.models.session import Session as SessionModel
        row = db.get(SessionModel, session_id)
        if row:
            row.status = "completed"
            db.commit()
    finally:
        db.close()
        engine.dispose()


def complete_all_active_for_pedestal(pedestal_id: int) -> None:
    """Mark every active session for a pedestal as completed."""
    engine = create_engine(_TEST_DB, connect_args={"check_same_thread": False})
    S = sessionmaker(bind=engine)
    db = S()
    try:
        from app.models.session import Session as SessionModel
        rows = db.query(SessionModel).filter(
            SessionModel.pedestal_id == pedestal_id,
            SessionModel.status == "active",
        ).all()
        for r in rows:
            r.status = "completed"
        db.commit()
    finally:
        db.close()
        engine.dispose()
