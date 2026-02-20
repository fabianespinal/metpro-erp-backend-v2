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
        contact_id=quote.contact_id,       # <-- was missing, caused the 500
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
    # Load quote joined with the selected contact (not company default)
    quote = service.get_quote_with_contact(quote_id)

    # Build client dict — keys must match what layout_utils.py looks for
    client = {
        "company_name": quote["company_name"],
        "address":      quote.get("company_address", ""),
        "contact_name": quote.get("contact_name", ""),
        "email":        quote.get("contact_email", ""),
        "phone":        quote.get("contact_phone", ""),
    }

    # Parse included_charges — may come back as dict or JSON string
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
    return service.delete_quote(quote_id)
