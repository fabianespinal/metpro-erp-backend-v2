import json
import base64

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional

from .models import Invoice, InvoiceCreate, InvoiceStatusUpdate
from . import service
from auth.service import verify_token

from invoices.payments.models import PaymentCreate
from invoices.payments.service import create_payment

from database import get_db_connection

from email_service import send_invoice_email
from invoices.service import calculate_invoice_totals
from pdf.builder_invoice import create_invoice_pdf

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.post("/", response_model=Invoice)
def create_invoice(invoice: InvoiceCreate, current_user: dict = Depends(verify_token)):
    result = service.create_invoice_from_quote(invoice.quote_id, invoice.notes)
    return Invoice(**result)


@router.get("/", response_model=List[Invoice])
def get_invoices(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(verify_token),
):
    invoices = service.get_all_invoices(client_id, status)
    return [Invoice(**inv) for inv in invoices]


@router.post("/{invoice_id}/send")
def send_invoice(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Send invoice PDF to client via email"""

    invoice = service.get_invoice_with_contact(invoice_id)

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    client = {
        "company_name": invoice["company_name"],
        "address": invoice.get("company_address", ""),
        "contact_name": invoice.get("contact_name", ""),
        "email": invoice.get("contact_email", ""),
        "phone": invoice.get("contact_phone", ""),
    }

    raw_charges = invoice.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    items = invoice.get("items", [])
    totals = calculate_invoice_totals(items, raw_charges)

    pdf_stream = create_invoice_pdf(
        doc_type="FACTURA",
        doc_id=invoice["invoice_number"],
        doc_date=str(invoice["invoice_date"])[:10] if invoice.get("invoice_date") else "",
        client=client,
        project_name=invoice.get("notes", ""),
        notes=invoice.get("notes", ""),
        items=items,
        charges=raw_charges,
        items_total=totals["items_total"],
        total_discounts=totals["total_discounts"],
        items_after_discount=totals["items_after_discount"],
        supervision=totals["supervision"],
        supervision_pct=raw_charges.get("supervision_percentage", 10.0),
        admin=totals["admin"],
        admin_pct=raw_charges.get("admin_percentage", 4.0),
        insurance=totals["insurance"],
        insurance_pct=raw_charges.get("insurance_percentage", 1.0),
        transport=totals["transport"],
        transport_pct=raw_charges.get("transport_percentage", 3.0),
        contingency=totals["contingency"],
        contingency_pct=raw_charges.get("contingency_percentage", 3.0),
        subtotal_general=totals["subtotal_general"],
        itbis=totals["itbis"],
        grand_total=totals["grand_total"],
        payment_terms=None,
        valid_until=None,
        amount_paid=invoice.get("amount_paid", 0),
        amount_due=invoice.get("amount_due", 0),
    )

    pdf_bytes = pdf_stream.read()

    # FIXED: Correct signature for send_invoice_email
    send_invoice_email(
        contact_email=invoice["contact_email"],
        contact_name=invoice["contact_name"],
        company_name=invoice["company_name"],
        project_name=invoice.get("notes", ""),
        invoice_id=str(invoice["invoice_number"]),
        pdf_bytes=pdf_bytes,
    )

    return {"message": "Factura enviada exitosamente", "invoice_id": invoice_id}


@router.get("/{invoice_id}", response_model=Invoice)
def get_invoice(invoice_id: int, current_user: dict = Depends(verify_token)):
    result = service.get_invoice_by_id(invoice_id)
    return Invoice(**result)


@router.get("/number/{invoice_number}", response_model=Invoice)
def get_invoice_by_number(invoice_number: str, current_user: dict = Depends(verify_token)):
    result = service.get_invoice_by_number(invoice_number)
    return Invoice(**result)


@router.patch("/{invoice_id}/status", response_model=Invoice)
def update_invoice_status(
    invoice_id: int,
    status_update: InvoiceStatusUpdate,
    current_user: dict = Depends(verify_token),
):
    result = service.update_invoice_status(invoice_id, status_update.status)
    return Invoice(**result)


@router.delete("/{invoice_id}")
def delete_invoice(invoice_id: int, current_user: dict = Depends(verify_token)):
    return service.delete_invoice(invoice_id)


@router.post("/{invoice_id}/payments")
def add_payment(invoice_id: int, data: PaymentCreate):
    conn = get_db_connection()
    try:
        payment_id = create_payment(conn, invoice_id, data)
        return {"payment_id": payment_id}
    finally:
        conn.close()

@router.get("/{invoice_id}/public")
def get_public_invoice(invoice_id: int):
    """Public invoice view without authentication"""
    invoice = service.get_invoice_with_contact(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return invoice

@router.get("/{invoice_id}/public/pdf")
def get_public_invoice_pdf(invoice_id: int):
    """Public PDF download for invoices"""
    invoice = service.get_invoice_with_contact(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    raw_charges = invoice.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    items = invoice.get("items", [])
    totals = calculate_invoice_totals(items, raw_charges)

    pdf_stream = create_invoice_pdf(
        doc_type="FACTURA",
        doc_id=invoice["invoice_number"],
        doc_date=str(invoice["invoice_date"])[:10] if invoice.get("invoice_date") else "",
        client={
            "company_name": invoice["company_name"],
            "address": invoice.get("company_address", ""),
            "contact_name": invoice.get("contact_name", ""),
            "email": invoice.get("contact_email", ""),
            "phone": invoice.get("contact_phone", ""),
        },
        project_name=invoice.get("notes", ""),
        notes=invoice.get("notes", ""),
        items=items,
        charges=raw_charges,
        items_total=totals["items_total"],
        total_discounts=totals["total_discounts"],
        items_after_discount=totals["items_after_discount"],
        supervision=totals["supervision"],
        supervision_pct=raw_charges.get("supervision_percentage", 10.0),
        admin=totals["admin"],
        admin_pct=raw_charges.get("admin_percentage", 4.0),
        insurance=totals["insurance"],
        insurance_pct=raw_charges.get("insurance_percentage", 1.0),
        transport=totals["transport"],
        transport_pct=raw_charges.get("transport_percentage", 3.0),
        contingency=totals["contingency"],
        contingency_pct=raw_charges.get("contingency_percentage", 3.0),
        subtotal_general=totals["subtotal_general"],
        itbis=totals["itbis"],
        grand_total=totals["grand_total"],
        payment_terms=None,
        valid_until=None,
        amount_paid=invoice.get("amount_paid", 0),
        amount_due=invoice.get("amount_due", 0),
    )

    pdf_bytes = pdf_stream.read()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=factura_{invoice_id}.pdf"
        }
    )