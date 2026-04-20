"""
Regression guard for H-2: concurrent/repeated calls to
create_invoice_for_session must never produce duplicate Invoice rows.

Session completion can be triggered from three code paths (operator stop,
customer stop, MQTT disconnect). Before the fix, a race between any two of
them could bypass the check-then-insert and create two invoices. The fix:
idempotent handler that catches IntegrityError and returns the existing row.
"""
from __future__ import annotations
import asyncio
import pytest

from sqlalchemy import text
from app.services.invoice_service import create_invoice_for_session
from app.models.session import Session
from app.auth.customer_models import Invoice, Customer
from app.auth.password import hash_password
from tests.backend.conftest import TestSession, TestUserSession, test_user_engine


@pytest.fixture
def session_with_customer():
    """Create a completed session whose customer_id is set, plus the customer row."""
    user_db = TestUserSession()
    db = TestSession()
    try:
        # Ensure the UNIQUE index on invoices.session_id exists (mirrors prod migration).
        with test_user_engine.connect() as conn:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_session_id ON invoices(session_id)"))
            conn.commit()

        customer = Customer(
            email="idem-test@example.com",
            password_hash=hash_password("x"),
            name="Idem Test",
        )
        user_db.add(customer)
        user_db.commit()
        user_db.refresh(customer)

        session = Session(
            pedestal_id=1,
            socket_id=1,
            type="electricity",
            status="completed",
            energy_kwh=2.5,
            customer_id=customer.id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        yield (db, user_db, session, customer)
    finally:
        # Cleanup
        user_db.query(Invoice).filter(Invoice.session_id == session.id).delete()
        user_db.query(Customer).filter(Customer.id == customer.id).delete()
        user_db.commit()
        db.query(Session).filter(Session.id == session.id).delete()
        db.commit()
        db.close()
        user_db.close()


def test_second_call_returns_existing_invoice(session_with_customer):
    """Calling create_invoice_for_session twice on the same session returns one row."""
    db, user_db, session, _ = session_with_customer

    first = asyncio.run(create_invoice_for_session(db, user_db, session))
    second = asyncio.run(create_invoice_for_session(db, user_db, session))

    assert first is not None and second is not None
    assert first.id == second.id, "Second call must return the existing invoice, not a new one"

    count = user_db.query(Invoice).filter(Invoice.session_id == session.id).count()
    assert count == 1, f"Expected exactly 1 invoice for session, got {count}"


def test_integrity_violation_returns_existing(session_with_customer):
    """If the UNIQUE index raises, handler must fetch and return the existing row."""
    db, user_db, session, customer = session_with_customer

    # Simulate a pre-existing invoice (as if another code path won the race)
    preexisting = Invoice(
        session_id=session.id,
        customer_id=customer.id,
        energy_kwh=1.0,
        total_eur=0.30,
    )
    user_db.add(preexisting)
    user_db.commit()
    user_db.refresh(preexisting)

    # Now the "losing" path runs; must not raise, must return preexisting.
    result = asyncio.run(create_invoice_for_session(db, user_db, session))
    assert result is not None
    assert result.id == preexisting.id

    count = user_db.query(Invoice).filter(Invoice.session_id == session.id).count()
    assert count == 1
