"""Customer service order submission and admin management."""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..auth.user_database import get_user_db
from ..auth.contract_models import ServiceOrder
from ..auth.customer_models import Customer
from ..auth.dependencies import require_admin
from ..auth.customer_dependencies import require_customer
from ..auth.models import User

router = APIRouter(tags=["service-orders"])


# ─── Pydantic schemas ──────────────────────────────────────────────────────────

_ALLOWED_SERVICE_TYPES = {
    "electrical", "water", "maintenance", "cleaning", "security", "other"
}


class ServiceOrderCreate(BaseModel):
    service_type: str = Field(..., min_length=1, max_length=60)
    notes: Optional[str] = Field(None, max_length=1000)


class ServiceOrderResponse(BaseModel):
    id: int
    customer_id: int
    service_type: str
    notes: Optional[str] = None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminServiceOrderResponse(BaseModel):
    id: int
    customer_id: int
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    service_type: str
    notes: Optional[str] = None
    status: str
    created_at: datetime


# ─── Customer endpoints ────────────────────────────────────────────────────────

@router.post("/api/customer/service-orders/", response_model=ServiceOrderResponse)
def submit_service_order(
    body: ServiceOrderCreate,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    order = ServiceOrder(
        customer_id=customer.id,
        service_type=body.service_type,
        notes=body.notes,
        status="pending",
        created_at=datetime.utcnow(),
    )
    user_db.add(order)
    user_db.commit()
    user_db.refresh(order)
    return order


@router.get("/api/customer/service-orders/mine", response_model=list[ServiceOrderResponse])
def my_service_orders(
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    return (
        user_db.query(ServiceOrder)
        .filter(ServiceOrder.customer_id == customer.id)
        .order_by(ServiceOrder.created_at.desc())
        .all()
    )


# ─── Admin endpoints ───────────────────────────────────────────────────────────

@router.get("/api/admin/service-orders/", response_model=list[AdminServiceOrderResponse])
def admin_list_service_orders(
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    orders = (
        user_db.query(ServiceOrder)
        .order_by(ServiceOrder.created_at.desc())
        .all()
    )
    rows = []
    for o in orders:
        customer = user_db.get(Customer, o.customer_id)
        rows.append(AdminServiceOrderResponse(
            id=o.id,
            customer_id=o.customer_id,
            customer_name=customer.name if customer else None,
            customer_email=customer.email if customer else None,
            service_type=o.service_type,
            notes=o.notes,
            status=o.status,
            created_at=o.created_at,
        ))
    return rows
