from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from . import service
from auth.service import require_auth

router = APIRouter(prefix='/pdf', tags=['pdf'])

# Quote PDF endpoints
@router.get('/quotes/{quote_id}')
def get_quote_pdf(quote_id: str, current_user: dict = Depends(require_auth)):
    """Generate quote PDF"""
    return service.generate_quote_pdf(quote_id, current_user)

# Invoice PDF endpoints
@router.get('/invoices/{invoice_id}')
def get_invoice_pdf(invoice_id: int, current_user: dict = Depends(require_auth)):
    """Generate invoice PDF"""
    return service.generate_invoice_pdf(invoice_id, current_user)

@router.get('/invoices/{invoice_id}/conduce')
def get_conduce_pdf(invoice_id: int, current_user: dict = Depends(require_auth)):
    """Generate conduce (delivery note) PDF for invoice"""
    return service.generate_conduce_pdf(invoice_id, current_user)
