"""
Regression guard for C-3: V1 and V2 water valves must produce independent
sessions. Before the fix, both mapped to socket_id=None so activating V2 while
V1 was active silently found V1's session and returned early — V2's usage was
unmetered.
"""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import patch

from app.services.mqtt_handlers import _handle_event_outlet_activated, _handle_event_session_ended
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


def _activate(db, outlet_id: str):
    asyncio.run(_handle_event_outlet_activated(
        db=db,
        pedestal_id=1,
        outlet_id=outlet_id,
        resource="WATER",
        data={"device": {"cabinetId": "TEST"}},
    ))


def _end(db, outlet_id: str):
    asyncio.run(_handle_event_session_ended(
        db=db,
        pedestal_id=1,
        outlet_id=outlet_id,
        resource="WATER",
        data={"totals": {"volumeL": 5.0}},
    ))


@patch("app.services.mqtt_handlers.ws_manager.broadcast")
def test_v1_and_v2_create_separate_sessions(_broadcast, clean_sessions):
    """Activating V1 then V2 must produce two distinct rows with socket_id=1,2."""
    db = clean_sessions
    _activate(db, "V1")
    _activate(db, "V2")

    sessions = db.query(Session).filter(Session.type == "water", Session.status == "active").all()
    socket_ids = sorted(s.socket_id for s in sessions)
    assert socket_ids == [1, 2], f"Expected water sessions for both V1 and V2, got socket_ids={socket_ids}"
    assert len(sessions) == 2


@patch("app.services.mqtt_handlers.ws_manager.broadcast")
def test_v1_end_does_not_affect_v2(_broadcast, clean_sessions):
    """Completing V1's session must leave V2's session untouched."""
    db = clean_sessions
    _activate(db, "V1")
    _activate(db, "V2")

    _end(db, "V1")

    v1 = db.query(Session).filter_by(type="water", socket_id=1).order_by(Session.id.desc()).first()
    v2 = db.query(Session).filter_by(type="water", socket_id=2).order_by(Session.id.desc()).first()
    assert v1 is not None and v1.status == "completed"
    assert v2 is not None and v2.status == "active", "V2 session should still be active after V1 ends"
