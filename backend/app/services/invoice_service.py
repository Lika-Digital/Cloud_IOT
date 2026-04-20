"""Invoice creation service — called when a session completes."""
import logging
import traceback
from datetime import datetime
from sqlalchemy.orm import Session as DBSession
from ..models.session import Session
from ..auth.customer_models import BillingConfig, Invoice

logger = logging.getLogger(__name__)


async def create_invoice_for_session(
    pedestal_db: DBSession,
    user_db: DBSession,
    session: Session,
) -> Invoice | None:
    """Create an Invoice for a completed session. Returns None if session has no customer or already invoiced."""
    if not session.customer_id:
        return None

    # Prevent double invoice
    existing = user_db.query(Invoice).filter(Invoice.session_id == session.id).first()
    if existing:
        return existing

    billing = user_db.get(BillingConfig, 1)
    kwh_price = billing.kwh_price_eur if billing else 0.30
    liter_price = billing.liter_price_eur if billing else 0.015

    energy_kwh = session.energy_kwh or 0.0
    water_liters = session.water_liters or 0.0

    energy_cost = round(energy_kwh * kwh_price, 4)
    water_cost = round(water_liters * liter_price, 4)
    total = round(energy_cost + water_cost, 4)

    invoice = Invoice(
        session_id=session.id,
        customer_id=session.customer_id,
        energy_kwh=energy_kwh if session.type == "electricity" else None,
        water_liters=water_liters if session.type == "water" else None,
        energy_cost_eur=energy_cost if session.type == "electricity" else None,
        water_cost_eur=water_cost if session.type == "water" else None,
        total_eur=total,
        paid=0,
        created_at=datetime.utcnow(),
    )
    from sqlalchemy.exc import IntegrityError
    try:
        user_db.add(invoice)
        user_db.commit()
        user_db.refresh(invoice)
    except IntegrityError:
        # Another code path (operator stop + customer stop + MQTT disconnect
        # can race) already inserted an invoice for this session. Return the
        # winning row so callers stay idempotent.
        user_db.rollback()
        existing = user_db.query(Invoice).filter(Invoice.session_id == session.id).first()
        if existing:
            logger.info(f"Invoice for session {session.id} already existed (race); returning id={existing.id}")
            return existing
        # UNIQUE violation with no row visible — propagate, this is genuinely broken.
        raise
    except Exception as e:
        user_db.rollback()
        try:
            from .error_log_service import log_error
            log_error(
                "system", "invoice_service",
                f"Failed to persist invoice for session {session.id}: {e}",
                details=traceback.format_exc(),
            )
        except Exception:
            pass
        raise

    logger.info(f"Created invoice {invoice.id} for session {session.id}, customer {session.customer_id}, total €{total}")

    # Broadcast invoice_created WS event (best-effort, never raises)
    try:
        from ..services.websocket_manager import ws_manager
        await ws_manager.broadcast({
            "event": "invoice_created",
            "data": {
                "invoice_id": invoice.id,
                "session_id": session.id,
                "customer_id": session.customer_id,
                "total_eur": total,
            },
        })
    except Exception as e:
        logger.warning(f"Could not broadcast invoice_created: {e}")

    return invoice
