from fastapi import APIRouter, Depends
from typing import List, Optional
from .models import QuoteCreate, StatusUpdate, QuoteUpdate
from . import service
from auth.service import verify_token

router = APIRouter(prefix='/quotes', tags=['quotes'])

@router.post('/')
def create_quote(quote: QuoteCreate, current_user: dict = Depends(verify_token)):
    """Create a new quote"""
    items = [item.dict() for item in quote.items]
    charges = quote.included_charges.dict()
    result = service.create_quote(
        quote.client_id,
        quote.project_name,
        quote.notes,
        items,
        charges
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
    """Convert approved quote to invoice - returns invoice data with proper fields"""
    invoice = service.convert_quote_to_invoice(quote_id)
    # Return invoice data with invoice_id and invoice_number for frontend
    return {
        "invoice_id": invoice["id"],
        "invoice_number": invoice["invoice_number"],
        "quote_id": invoice["quote_id"],
        "client_id": invoice["client_id"],
        "total_amount": invoice["total_amount"],
        "status": invoice["status"],
        "invoice_date": invoice["invoice_date"],
        "message": f"Quote {quote_id} converted to invoice {invoice['invoice_number']}"
    }

@router.delete('/{quote_id}')
def delete_quote(quote_id: str, current_user: dict = Depends(verify_token)):
    """Delete a quote"""
    return service.delete_quote(quote_id)
