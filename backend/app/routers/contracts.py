"""Contract template management and customer contract signing."""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
import io

from ..auth.user_database import get_user_db
from ..auth.contract_models import ContractTemplate, CustomerContract
from ..auth.customer_models import Customer
from ..auth.dependencies import require_admin
from ..auth.customer_dependencies import require_customer
from ..auth.models import User
from ..services.pdf_service import make_contract_pdf

router = APIRouter(tags=["contracts"])


# ─── Pydantic schemas ──────────────────────────────────────────────────────────

class TemplateCreate(BaseModel):
    title: str
    body: str
    validity_days: int = 365
    notify_on_register: bool = True


class TemplateUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    validity_days: Optional[int] = None
    notify_on_register: Optional[bool] = None
    active: Optional[bool] = None


class TemplateResponse(BaseModel):
    id: int
    title: str
    body: str
    validity_days: int
    active: bool
    notify_on_register: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SignRequest(BaseModel):
    signature_data: str = Field(..., max_length=500_000)  # base64 PNG, cap at ~500 KB


class ContractResponse(BaseModel):
    id: int
    customer_id: int
    template_id: int
    signed_at: datetime
    valid_until: Optional[datetime] = None
    status: str
    template_title: Optional[str] = None

    model_config = {"from_attributes": True}


class AdminContractResponse(BaseModel):
    id: int
    customer_id: int
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    template_id: int
    template_title: Optional[str] = None
    signed_at: datetime
    valid_until: Optional[datetime] = None
    status: str

    model_config = {"from_attributes": True}


# ─── Admin: template management ───────────────────────────────────────────────

@router.get("/api/contracts/templates", response_model=list[TemplateResponse])
def list_templates(
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    return user_db.query(ContractTemplate).order_by(ContractTemplate.id).all()


@router.post("/api/contracts/templates", response_model=TemplateResponse)
def create_template(
    body: TemplateCreate,
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    tpl = ContractTemplate(**body.model_dump())
    user_db.add(tpl)
    user_db.commit()
    user_db.refresh(tpl)
    return tpl


@router.patch("/api/contracts/templates/{template_id}", response_model=TemplateResponse)
def update_template(
    template_id: int,
    body: TemplateUpdate,
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    tpl = user_db.get(ContractTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(tpl, field, value)
    user_db.commit()
    user_db.refresh(tpl)
    return tpl


# ─── Admin: signed contracts ───────────────────────────────────────────────────

@router.get("/api/admin/contracts", response_model=list[AdminContractResponse])
def admin_list_contracts(
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    contracts = user_db.query(CustomerContract).order_by(CustomerContract.signed_at.desc()).all()
    rows = []
    for c in contracts:
        customer = user_db.get(Customer, c.customer_id)
        template = user_db.get(ContractTemplate, c.template_id)
        rows.append(AdminContractResponse(
            id=c.id,
            customer_id=c.customer_id,
            customer_name=customer.name if customer else None,
            customer_email=customer.email if customer else None,
            template_id=c.template_id,
            template_title=template.title if template else None,
            signed_at=c.signed_at,
            valid_until=c.valid_until,
            status=c.status,
        ))
    return rows


@router.get("/api/admin/contracts/{contract_id}/pdf")
def admin_download_contract_pdf(
    contract_id: int,
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    contract = user_db.get(CustomerContract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    customer = user_db.get(Customer, contract.customer_id)
    template = user_db.get(ContractTemplate, contract.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        pdf_bytes = make_contract_pdf(
            template_title=template.title,
            template_body=template.body,
            customer_name=customer.name if customer else None,
            customer_email=customer.email if customer else "unknown",
            signed_at=contract.signed_at,
            valid_until=contract.valid_until,
            signature_data=contract.signature_data,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="PDF generation failed. Please try again later.")
    filename = f"contract_{contract_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Customer: contract flow ──────────────────────────────────────────────────

@router.get("/api/customer/contracts/pending", response_model=list[TemplateResponse])
def get_pending_contracts(
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    """Return active templates the customer has not yet signed."""
    active_templates = (
        user_db.query(ContractTemplate)
        .filter(ContractTemplate.active == True)  # noqa: E712
        .all()
    )
    signed_template_ids = {
        cc.template_id
        for cc in user_db.query(CustomerContract)
        .filter(CustomerContract.customer_id == customer.id)
        .all()
    }
    return [t for t in active_templates if t.id not in signed_template_ids]


@router.post("/api/customer/contracts/{template_id}/sign", response_model=ContractResponse)
def sign_contract(
    template_id: int,
    body: SignRequest,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    template = user_db.get(ContractTemplate, template_id)
    if not template or not template.active:
        raise HTTPException(status_code=404, detail="Template not found or inactive")

    # Check not already signed
    existing = (
        user_db.query(CustomerContract)
        .filter(
            CustomerContract.customer_id == customer.id,
            CustomerContract.template_id == template_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Already signed")

    now = datetime.utcnow()
    valid_until = now + timedelta(days=template.validity_days)

    contract = CustomerContract(
        customer_id=customer.id,
        template_id=template_id,
        signature_data=body.signature_data,
        signed_at=now,
        valid_until=valid_until,
        status="active",
    )
    user_db.add(contract)
    user_db.commit()
    user_db.refresh(contract)

    result = ContractResponse.model_validate(contract)
    result.template_title = template.title
    return result


@router.get("/api/customer/contracts/mine", response_model=list[ContractResponse])
def my_contracts(
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    contracts = (
        user_db.query(CustomerContract)
        .filter(CustomerContract.customer_id == customer.id)
        .order_by(CustomerContract.signed_at.desc())
        .all()
    )
    rows = []
    for c in contracts:
        template = user_db.get(ContractTemplate, c.template_id)
        row = ContractResponse.model_validate(c)
        row.template_title = template.title if template else None
        rows.append(row)
    return rows


@router.get("/api/customer/contracts/{contract_id}/pdf")
def download_contract_pdf(
    contract_id: int,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    contract = user_db.get(CustomerContract, contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    if contract.customer_id != customer.id:
        raise HTTPException(status_code=403, detail="Not your contract")
    template = user_db.get(ContractTemplate, contract.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        pdf_bytes = make_contract_pdf(
            template_title=template.title,
            template_body=template.body,
            customer_name=customer.name,
            customer_email=customer.email,
            signed_at=contract.signed_at,
            valid_until=contract.valid_until,
            signature_data=contract.signature_data,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="PDF generation failed. Please try again later.")
    filename = f"contract_{contract_id}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
