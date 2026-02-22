"""Billing configuration and spending overview (admin only)."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from ..auth.user_database import get_user_db
from ..database import get_db
from ..auth.customer_models import BillingConfig, Invoice, Customer
from ..auth.dependencies import require_admin
from ..auth.models import User
from ..models.session import Session
from ..schemas.customer import (
    BillingConfigResponse, BillingConfigUpdate,
    CustomerSpendingRow, CustomerListRow,
)

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/config", response_model=BillingConfigResponse)
def get_billing_config(
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    config = user_db.get(BillingConfig, 1)
    if not config:
        raise HTTPException(status_code=404, detail="Billing config not found")
    return config


@router.put("/config", response_model=BillingConfigResponse)
def update_billing_config(
    body: BillingConfigUpdate,
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
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


@router.get("/spending", response_model=list[CustomerSpendingRow])
def get_spending_overview(
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
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


@router.get("/customers", response_model=list[CustomerListRow])
def get_customers(
    user_db: DBSession = Depends(get_user_db),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
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
