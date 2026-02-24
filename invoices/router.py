import json

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional

from .models import Invoice, InvoiceCreate, InvoiceStatusUpdate
from . import service
from auth.service import verify_token

from invoices.payments.models import PaymentCreate
from invoices.payments.service import create_payment

from database import get_db_connection

router = APIRouter(prefix='/invoices', tags=['invoices'])


@router.post('/', response_model=Invoice)
def create_invoice(invoice: InvoiceCreate, current_user: dict = Depends(verify_token)):
    result = service.create_invoice_from_quote(invoice.quote_id, invoice.notes)
    return Invoice(**result)


@router.get('/', response_model=List[Invoice])
def get_invoices(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    invoices = service.get_all_invoices(client_id, status)
    return [Invoice(**inv) for inv in invoices]

@router.post('/{invoice_id}/send')
def send_invoice(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Send invoice PDF to client via email"""
    from email_service import send_invoice_email
    from invoices.service import calculate_invoice_totals
    from pdf.builder_invoice import create_invoice_pdf

    invoice = service.get_invoice_with_contact(invoice_id)

    client = {
        "company_name": invoice["company_name"],
        "address":      invoice.get("company_address", ""),
        "contact_name": invoice.get("contact_name", ""),
        "email":        invoice.get("contact_email", ""),
        "phone":        invoice.get("contact_phone", ""),
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

    send_invoice_email(
        contact_email=invoice["contact_email"],
        contact_name=invoice["contact_name"],
        company_name=invoice["company_name"],
        project_name=invoice.get("notes", ""),
        invoice_id=str(invoice["invoice_number"]),
        pdf_bytes=pdf_bytes,
    )

    return {"message": "Factura enviada exitosamente", "invoice_id": invoice_id}


@router.get('/{invoice_id}', response_model=Invoice)
def get_invoice(invoice_id: int, current_user: dict = Depends(verify_token)):
    result = service.get_invoice_by_id(invoice_id)
    return Invoice(**result)


@router.get('/number/{invoice_number}', response_model=Invoice)
def get_invoice_by_number(invoice_number: str, current_user: dict = Depends(verify_token)):
    result = service.get_invoice_by_number(invoice_number)
    return Invoice(**result)


@router.patch('/{invoice_id}/status', response_model=Invoice)
def update_invoice_status(
    invoice_id: int,
    status_update: InvoiceStatusUpdate,
    current_user: dict = Depends(verify_token)
):
    result = service.update_invoice_status(invoice_id, status_update.status)
    return Invoice(**result)


@router.delete('/{invoice_id}')
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

        @router.post("/{invoice_id}/send")
def send_invoice_to_client(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Generate PDF, build public link, render email template, and send invoice to client."""

    # 1. Fetch invoice
    invoice = service.get_invoice_by_id(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    client = invoice.get("client")
    if not client:
        raise HTTPException(status_code=400, detail="Invoice has no client assigned")

    client_email = client.get("email")
    if not client_email:
        raise HTTPException(
            status_code=400,
            detail="Client does not have an email address. Please update the client record."
        )

    # 2. Generate PDF using your existing PDF builder
    try:
        pdf_bytes = create_invoice_pdf(
            doc_type="FACTURA",
            doc_id=invoice["invoice_id"],
            doc_date=invoice.get("created_at") or invoice.get("updated_at") or "",
            client=invoice["client"],
            project_name=invoice["project_name"],
            notes=invoice["notes"],
            items=invoice["items"],
            charges=invoice["charges"],
            items_total=invoice["items_total"],
            total_discounts=invoice["total_discounts"],
            items_after_discount=invoice["items_after_discount"],
            supervision=invoice["supervision"],
            supervision_pct=invoice["supervision_pct"],
            admin=invoice["admin"],
            admin_pct=invoice["admin_pct"],
            insurance=invoice["insurance"],
            insurance_pct=invoice["insurance_pct"],
            transport=invoice["transport"],
            transport_pct=invoice["transport_pct"],
            contingency=invoice["contingency"],
            contingency_pct=invoice["contingency_pct"],
            subtotal_general=invoice["subtotal_general"],
            itbis=invoice["itbis"],
            grand_total=invoice["grand_total"],
            payment_terms=invoice.get("payment_terms"),
            due_date=invoice.get("due_date"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    # 3. Build public link
    public_url = f"https://app.metprord.com/invoices/{invoice_id}"

    # 4. Render branded METPRO email template
    html = render_invoice_email(
        client_name=client.get("contact_name") or client.get("company_name"),
        invoice_id=invoice_id,
        public_url=public_url
    )

    # 5. Prepare email payload
    params = {
        "from": "info@metprord.com",  # after domain verification
        "to": [client_email],
        "subject": f"METPRO Factura #{invoice_id}",
        "html": html,
        "attachments": [
            {
                "filename": f"factura_{invoice_id}.pdf",
                "content": base64.b64encode(pdf_bytes).decode(),
            }
        ],
    }

    # 6. Send email via Resend
    try:
        email = resend.Emails.send(params)
        return {"status": "sent", "email_id": email.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email sending failed: {str(e)}")
