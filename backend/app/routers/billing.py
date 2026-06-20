"""Billing configuration and spending overview (admin only)."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession
from ..auth.user_database import get_user_db
from ..database import get_db
from ..auth.customer_models import BillingConfig, Invoice, Customer
from ..auth.dependencies import require_any_role, require_control
from ..auth.models import User
from ..models.session import Session
from ..models.energy_interval import EnergyInterval
from ..schemas.customer import (
    BillingConfigResponse, BillingConfigUpdate,
    CustomerSpendingRow, CustomerListRow, SessionDetailRow,
)

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/config", response_model=BillingConfigResponse)
def get_billing_config(
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_any_role),
):
    config = user_db.get(BillingConfig, 1)
    if not config:
        raise HTTPException(status_code=404, detail="Billing config not found")
    return config


@router.put("/config", response_model=BillingConfigResponse)
def update_billing_config(
    body: BillingConfigUpdate,
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_control),
):
    config = user_db.get(BillingConfig, 1)
    if not config:
        config = BillingConfig(id=1, kwh_price_eur=body.kwh_price_eur, liter_price_eur=body.liter_price_eur)
        user_db.add(config)
    else:
        config.kwh_price_eur = body.kwh_price_eur
        config.liter_price_eur = body.liter_price_eur
        config.updated_at = datetime.utcnow()
    user_db.commit()
    user_db.refresh(config)
    return config


@router.get("/daily")
def get_daily_billing(
    start: str | None = Query(None, description="Inclusive 'YYYY-MM-DD'"),
    end: str | None = Query(None, description="Inclusive 'YYYY-MM-DD'"),
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_any_role),
):
    """v3.35 — daily energy-billing rollup from the 15-min interval ledger.

    One row per (day, socket, attribution): ``origin`` is "berth-marina" for
    Smart-Mode-OFF standalone draws (keyed by socket + ``berth_ref``), else
    "customer" / "nfc" / "operator". ``cost_eur`` = summed kWh x current price.
    Readable by every operator; computed on read so it never drifts.
    """
    day = func.date(EnergyInterval.interval_start)
    q = db.query(
        day.label("date"),
        EnergyInterval.pedestal_id,
        EnergyInterval.socket_id,
        EnergyInterval.origin,
        EnergyInterval.customer_id,
        EnergyInterval.nfc_user_id,
        EnergyInterval.berth_ref,
        func.sum(EnergyInterval.kwh).label("kwh"),
    )
    if start:
        q = q.filter(day >= start)
    if end:
        q = q.filter(day <= end)
    q = q.group_by(
        day, EnergyInterval.pedestal_id, EnergyInterval.socket_id,
        EnergyInterval.origin, EnergyInterval.customer_id,
        EnergyInterval.nfc_user_id, EnergyInterval.berth_ref,
    ).order_by(day.desc(), EnergyInterval.pedestal_id, EnergyInterval.socket_id)
    rows = q.all()

    cfg = user_db.get(BillingConfig, 1)
    price = cfg.kwh_price_eur if cfg else 0.30

    cust_ids = {r.customer_id for r in rows if r.customer_id}
    names: dict[int, str] = {}
    if cust_ids:
        for c in user_db.query(Customer).filter(Customer.id.in_(cust_ids)).all():
            names[c.id] = c.name or c.email or f"#{c.id}"

    out = []
    for r in rows:
        kwh = round(r.kwh or 0.0, 4)
        out.append({
            "date": r.date,
            "pedestal_id": r.pedestal_id,
            "socket_id": r.socket_id,
            "origin": r.origin,
            "customer_id": r.customer_id,
            "customer_name": names.get(r.customer_id),
            "nfc_user_id": r.nfc_user_id,
            "berth_ref": r.berth_ref,
            "kwh": kwh,
            "cost_eur": round(kwh * price, 4),
        })
    return out


@router.get("/spending", response_model=list[CustomerSpendingRow])
def get_spending_overview(
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_any_role),
):
    invoices = user_db.query(Invoice).filter(Invoice.customer_id.isnot(None)).all()
    # Aggregate per customer
    from collections import defaultdict
    agg: dict[int, dict] = defaultdict(lambda: {
        "session_count": 0, "total_kwh": 0.0, "total_liters": 0.0, "total_eur": 0.0
    })
    for inv in invoices:
        a = agg[inv.customer_id]
        a["session_count"] += 1
        a["total_kwh"] += inv.energy_kwh or 0.0
        a["total_liters"] += inv.water_liters or 0.0
        a["total_eur"] += inv.total_eur or 0.0

    rows = []
    for customer_id, data in agg.items():
        customer = user_db.get(Customer, customer_id)
        rows.append(CustomerSpendingRow(
            customer_id=customer_id,
            customer_name=customer.name if customer else None,
            customer_email=customer.email if customer else "?",
            session_count=data["session_count"],
            total_kwh=round(data["total_kwh"], 4),
            total_liters=round(data["total_liters"], 4),
            total_eur=round(data["total_eur"], 4),
        ))
    return rows


@router.get("/spending/detail", response_model=list[SessionDetailRow])
def get_spending_detail(
    user_db: DBSession = Depends(get_user_db),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    invoices = user_db.query(Invoice).filter(Invoice.customer_id.isnot(None)).all()
    rows = []
    for inv in invoices:
        customer = user_db.get(Customer, inv.customer_id)
        session = db.get(Session, inv.session_id)
        rows.append(SessionDetailRow(
            customer_id=inv.customer_id,
            customer_name=customer.name if customer else None,
            customer_email=customer.email if customer else "?",
            session_id=inv.session_id,
            session_type=session.type if session else "electricity",
            started_at=session.started_at if session else None,
            ended_at=session.ended_at if session else None,
            energy_kwh=inv.energy_kwh,
            water_liters=inv.water_liters,
            total_eur=inv.total_eur or 0.0,
            paid=bool(inv.paid),
        ))
    return rows


@router.get("/customers", response_model=list[CustomerListRow])
def get_customers(
    user_db: DBSession = Depends(get_user_db),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    customers = user_db.query(Customer).order_by(Customer.created_at.desc()).all()
    rows = []
    for c in customers:
        # Find active session
        active = (
            db.query(Session)
            .filter(Session.customer_id == c.id, Session.status.in_(["pending", "active"]))
            .first()
        )
        rows.append(CustomerListRow(
            id=c.id,
            email=c.email,
            name=c.name,
            ship_name=c.ship_name,
            active_session_id=active.id if active else None,
            active_session_type=active.type if active else None,
            created_at=c.created_at,
        ))
    return rows
