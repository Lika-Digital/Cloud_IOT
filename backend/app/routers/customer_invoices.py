"""Customer invoice endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from ..auth.user_database import get_user_db
from ..auth.customer_models import Customer, Invoice
from ..auth.customer_dependencies import require_customer
from ..schemas.customer import InvoiceResponse

router = APIRouter(prefix="/api/customer/invoices", tags=["customer-invoices"])


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
