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
