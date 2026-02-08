from fastapi import APIRouter, Depends
from . import service
from auth.service import verify_token

router = APIRouter(prefix='/pdf', tags=['pdf'])

@router.get('/quotes/{quote_id}')
def get_quote_pdf(quote_id: str, current_user: dict = Depends(verify_token)):
    """Generate and download quote PDF"""
    return service.generate_quote_pdf(quote_id)

@router.get('/invoices/{invoice_id}')
def get_invoice_pdf(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Generate and download invoice PDF"""
    return service.generate_invoice_pdf(invoice_id)
