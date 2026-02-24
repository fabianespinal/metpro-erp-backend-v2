from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from typing import Optional
from .models import QuoteCreate, StatusUpdate, QuoteUpdate
from . import service
from auth.service import verify_token
from pdf.builder_quote import create_quote_pdf
import json

router = APIRouter(prefix='/quotes', tags=['quotes'])


@router.post('/')
def create_quote(quote: QuoteCreate, current_user: dict = Depends(verify_token)):
    """Create a new quote"""
    items = [item.dict() for item in quote.items]
    charges = quote.included_charges.dict()
    result = service.create_quote(
        client_id=quote.client_id,
        contact_id=quote.contact_id,
        project_name=quote.project_name,
        notes=quote.notes,
        items=items,
        included_charges=charges,
        payment_terms=quote.payment_terms,
        valid_until=quote.valid_until,
    )
    return result


@router.get('/')
def get_quotes(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    """Get all quotes with optional filters"""
    return service.get_all_quotes(client_id, status)


@router.post('/{quote_id}/send')
def send_quote(quote_id: str, current_user: dict = Depends(verify_token)):
    """Send quote PDF to client via email"""
    from email_service import send_quote_email
    from quotes.service import calculate_quote_totals

    quote = service.get_quote_with_contact(quote_id)

    client = {
        "company_name": quote["company_name"],
        "address":      quote.get("company_address", ""),
        "contact_name": quote.get("contact_name", ""),
        "email":        quote.get("contact_email", ""),
        "phone":        quote.get("contact_phone", ""),
    }

    raw_charges = quote.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    items = quote.get("items", [])
    totals = calculate_quote_totals(items, raw_charges)

    pdf_stream = create_quote_pdf(
        doc_type="COTIZACIÓN",
        doc_id=quote["quote_id"],
        doc_date=str(quote["created_at"])[:10] if quote.get("created_at") else "",
        client=client,
        project_name=quote.get("project_name", ""),
        notes=quote.get("notes", ""),
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
        payment_terms=quote.get("payment_terms"),
        valid_until=str(quote["valid_until"]) if quote.get("valid_until") else None,
    )

    pdf_bytes = pdf_stream.read()

    send_quote_email(
        contact_email=quote["contact_email"],
        contact_name=quote["contact_name"],
        company_name=quote["company_name"],
        project_name=quote.get("project_name", ""),
        quote_id=quote_id,
        pdf_bytes=pdf_bytes,
    )

    service.update_quote_status(quote_id, "Sent")

    return {"message": "Cotización enviada exitosamente", "quote_id": quote_id}


@router.get('/{quote_id}')
def get_quote(quote_id: str, current_user: dict = Depends(verify_token)):
    """Get a single quote"""
    return service.get_quote_by_id(quote_id)


@router.get('/{quote_id}/pdf')
def get_quote_pdf(quote_id: str, current_user: dict = Depends(verify_token)):
    """
    Generate and stream a quote PDF.
    Uses get_quote_with_contact so the PDF always reflects the selected
    contact — never the company default.
    """
    quote = service.get_quote_with_contact(quote_id)

    client = {
        "company_name": quote["company_name"],
        "address":      quote.get("company_address", ""),
        "contact_name": quote.get("contact_name", ""),
        "email":        quote.get("contact_email", ""),
        "phone":        quote.get("contact_phone", ""),
    }

    raw_charges = quote.get("included_charges") or {}
    if isinstance(raw_charges, str):
        raw_charges = json.loads(raw_charges)

    from quotes.service import calculate_quote_totals
    items = quote.get("items", [])
    totals = calculate_quote_totals(items, raw_charges)

    pdf_stream = create_quote_pdf(
        doc_type="COTIZACIÓN",
        doc_id=quote["quote_id"],
        doc_date=str(quote["created_at"])[:10] if quote.get("created_at") else "",
        client=client,
        project_name=quote.get("project_name", ""),
        notes=quote.get("notes", ""),
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
        payment_terms=quote.get("payment_terms"),
        valid_until=str(quote["valid_until"]) if quote.get("valid_until") else None,
    )

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=quote_{quote_id}.pdf"
        }
    )


@router.put('/{quote_id}')
def update_quote(
    quote_id: str,
    quote_update: QuoteUpdate,
    current_user: dict = Depends(verify_token)
):
    """Update an existing quote (Draft status only)"""
    return service.update_quote(quote_id, quote_update)


@router.patch('/{quote_id}/status')
def update_quote_status(
    quote_id: str,
    status_update: StatusUpdate,
    current_user: dict = Depends(verify_token)
):
    """Update quote status"""
    return service.update_quote_status(quote_id, status_update.status)


@router.post('/{quote_id}/duplicate')
def duplicate_quote(quote_id: str, current_user: dict = Depends(verify_token)):
    """Duplicate an existing quote with new ID"""
    return service.duplicate_quote(quote_id)


@router.post('/{quote_id}/convert-to-invoice')
def convert_to_invoice(quote_id: str, current_user: dict = Depends(verify_token)):
    """Convert approved quote to invoice"""
    invoice = service.convert_quote_to_invoice(quote_id)
    return {
        "invoice_id":     invoice["id"],
        "invoice_number": invoice["invoice_number"],
        "quote_id":       invoice["quote_id"],
        "client_id":      invoice["client_id"],
        "total_amount":   invoice["total_amount"],
        "status":         invoice["status"],
        "invoice_date":   invoice["invoice_date"],
        "message": f"Quote {quote_id} converted to invoice {invoice['invoice_number']}"
    }


@router.delete('/{quote_id}')
def delete_quote(quote_id: str, current_user: dict = Depends(verify_token)):
    """Delete a quote"""
<<<<<<< HEAD
    return service.delete_quote(quote_id)

@router.post("/{quote_id}/send")
def send_quote_to_client(quote_id: int, current_user: dict = Depends(verify_token)):
    """Generate PDF, build public link, render email template, and send quote to client."""

    # 1. Fetch quote
    quote = service.get_quote_by_id(quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    client = quote.get("client")
    if not client:
        raise HTTPException(status_code=400, detail="Quote has no client assigned")

    client_email = client.get("email")
    if not client_email:
        raise HTTPException(
            status_code=400,
            detail="Client does not have an email address. Please update the client record."
        )

    # 2. Generate PDF using your existing PDF builder
    try:
        pdf_bytes = create_quote_pdf(
            doc_type="COTIZACION",
            doc_id=quote["quote_id"],
            doc_date=quote.get("created_at") or quote.get("updated_at") or "",
            client=quote["client"],
            project_name=quote["project_name"],
            notes=quote["notes"],
            items=quote["items"],
            charges=quote["charges"],
            items_total=quote["items_total"],
            total_discounts=quote["total_discounts"],
            items_after_discount=quote["items_after_discount"],
            supervision=quote["supervision"],
            supervision_pct=quote["supervision_pct"],
            admin=quote["admin"],
            admin_pct=quote["admin_pct"],
            insurance=quote["insurance"],
            insurance_pct=quote["insurance_pct"],
            transport=quote["transport"],
            transport_pct=quote["transport_pct"],
            contingency=quote["contingency"],
            contingency_pct=quote["contingency_pct"],
            subtotal_general=quote["subtotal_general"],
            itbis=quote["itbis"],
            grand_total=quote["grand_total"],
            payment_terms=quote.get("payment_terms"),
            valid_until=quote.get("valid_until"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {str(e)}")

    # 3. Build public link
    public_url = f"https://app.metprord.com/quotes/{quote_id}"

    # 4. Render branded METPRO email template
    html = render_quote_email(
        client_name=client.get("contact_name") or client.get("company_name"),
        quote_id=quote_id,
        public_url=public_url
    )

    # 5. Prepare email payload
    params = {
        "from": "info@metprord.com",  # after domain verification
        "to": [client_email],
        "subject": f"METPRO Cotización #{quote_id}",
        "html": html,
        "attachments": [
            {
                "filename": f"cotizacion_{quote_id}.pdf",
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
=======
    return service.delete_quote(quote_id)
>>>>>>> dev
