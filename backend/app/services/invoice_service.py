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

    # ── DEAD CODE ON AN UNUSED PATH (noted 2026-10-01) ──────────────────────────────────
    #
    # `or 0.0` collapses None into zero, and None means "we could not measure it"
    # (consumption_source == "unknown"), not "the meter read zero". Writing a charge of
    # EUR 0.00 for an unmeasurable session would be exactly the zero/unknown collapse that
    # the register work was built to prevent — in the one place that produces an actual
    # charge.
    #
    # It is NOT a defect we tolerated. THE PEDESTAL DOES NOT ISSUE INVOICES. It reports
    # consumption and the ERP bills; this module is not on a live path, which is why the
    # line was left exactly as it is rather than spending effort on a question that does
    # not arise.
    #
    # If MODE 2 ever makes us the biller, START HERE. The decision needed is commercial,
    # not technical, and there were four candidate answers:
    #   (a) keep EUR 0.00 — the customer pays nothing and nobody notices;
    #   (b) write no invoice and flag the session for review — recommended, because the
    #       charge is a human decision at that point;
    #   (c) invoice the integration-derived comparison figure, labelled "estimated" — it is
    #       already stored alongside the register delta for exactly this kind of question;
    #   (d) refuse to complete the session — not viable, the customer has already unplugged.
    #
    # See docs/ui_v2_spec.md §1.4 and docs/engineering_notes.md rule 8.
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
