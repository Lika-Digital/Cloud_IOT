"""Customer invoice endpoints."""
import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession
from ..auth.user_database import get_user_db
from ..database import get_db
from ..auth.customer_models import Customer, Invoice
from ..auth.customer_dependencies import require_customer
from ..models.session import Session as SessionModel
from ..schemas.customer import InvoiceResponse
from ..services.pdf_service import make_invoice_pdf

router = APIRouter(prefix="/api/customer/invoices", tags=["customer-invoices"])


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: int,
    user_db: DBSession = Depends(get_user_db),
    db: DBSession = Depends(get_db),
    customer: Customer = Depends(require_customer),
):
    invoice = user_db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.customer_id != customer.id:
        raise HTTPException(status_code=403, detail="Not your invoice")
    session = db.get(SessionModel, invoice.session_id)
    pdf_bytes = make_invoice_pdf(
        invoice_id=invoice.id,
        customer_name=customer.name,
        customer_email=customer.email,
        session_id=invoice.session_id,
        session_type=session.type if session else "electricity",
        started_at=session.started_at if session else None,
        ended_at=session.ended_at if session else None,
        energy_kwh=invoice.energy_kwh,
        water_liters=invoice.water_liters,
        energy_cost_eur=invoice.energy_cost_eur,
        water_cost_eur=invoice.water_cost_eur,
        total_eur=invoice.total_eur,
        paid=bool(invoice.paid),
        created_at=invoice.created_at,
    )
    filename = f"invoice_{invoice_id:05d}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/mine", response_model=list[InvoiceResponse])
def my_invoices(
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    return (
        user_db.query(Invoice)
        .filter(Invoice.customer_id == customer.id)
        .order_by(Invoice.created_at.desc())
        .all()
    )


@router.post("/{invoice_id}/pay", response_model=InvoiceResponse)
def pay_invoice(
    invoice_id: int,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    invoice = user_db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.customer_id != customer.id:
        raise HTTPException(status_code=403, detail="Not your invoice")
    if invoice.paid:
        raise HTTPException(status_code=400, detail="Already paid")
    invoice.paid = 1
    user_db.commit()
    user_db.refresh(invoice)
    return invoice
