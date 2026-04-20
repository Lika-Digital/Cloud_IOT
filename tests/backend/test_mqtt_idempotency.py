"""
Regression guard for H-4: duplicate OutletActivated events (firmware retry on
lost ACK) must not create two active sessions for the same socket.

Before the fix, the handler ran get_active_for_socket() then create_pending()
without DB-level protection, so two rapid events from different paho threads
could both pass the check and insert. A partial UNIQUE index + IntegrityError
handling in create_pending now guarantees idempotency.
"""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import patch

from app.services.mqtt_handlers import _handle_event_outlet_activated
from app.models.session import Session
from tests.backend.conftest import TestSession


@pytest.fixture
def clean_sessions():
    db = TestSession()
    try:
        db.query(Session).delete()
        db.commit()
        yield db
    finally:
        db.rollback()
        db.query(Session).delete()
        db.commit()
        db.close()


@patch("app.services.mqtt_handlers.ws_manager.broadcast")
def test_duplicate_outlet_activated_creates_single_session(_broadcast, clean_sessions):
    """Two OutletActivated events for Q1 back-to-back must yield ONE active session."""
    db = clean_sessions

    async def fire():
        await _handle_event_outlet_activated(
            db=db, pedestal_id=1, outlet_id="Q1", resource="POWER",
            data={"device": {"cabinetId": "TEST"}},
        )

    asyncio.run(fire())
    asyncio.run(fire())

    active = db.query(Session).filter_by(
        pedestal_id=1, socket_id=1, type="electricity",
    ).filter(Session.status.in_(("pending", "active"))).all()
    assert len(active) == 1, f"Expected 1 active session, got {len(active)}"


def test_create_pending_returns_existing_on_integrity_error(clean_sessions):
    """If a row already exists in pending/active, create_pending must return it (not raise)."""
    from app.services.session_service import session_service
    db = clean_sessions

    first = session_service.create_pending(db, pedestal_id=1, socket_id=2, session_type="electricity")
    session_service.activate(db, first)

    # Second call — partial unique index should trigger IntegrityError inside
    # create_pending, which then falls back to returning the existing row.
    second = session_service.create_pending(db, pedestal_id=1, socket_id=2, session_type="electricity")

    assert second.id == first.id, "create_pending must return existing session on unique-violation race"
    count = db.query(Session).filter_by(pedestal_id=1, socket_id=2, type="electricity").count()
    assert count == 1
