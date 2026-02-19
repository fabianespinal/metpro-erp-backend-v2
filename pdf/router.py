from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from . import service
from auth.service import verify_token

router = APIRouter(prefix='/pdf', tags=['pdf'])

# Quote PDF endpoints
@router.get('/quotes/{quote_id}')
def get_quote_pdf(quote_id: str, current_user: dict = Depends(verify_token)):
    """Generate quote PDF"""
    return service.generate_quote_pdf(quote_id)

# Invoice PDF endpoints
@router.get('/invoices/{invoice_id}')
def get_invoice_pdf(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Generate invoice PDF"""
    return service.generate_invoice_pdf(invoice_id)

@router.get('/invoices/{invoice_id}/conduce')
def get_conduce_pdf(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Generate conduce (delivery note) PDF for invoice"""
    return service.generate_conduce_pdf(invoice_id)
