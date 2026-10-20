from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from . import service
from auth.service import require_auth

router = APIRouter(prefix='/pdf', tags=['pdf'])

# Quote PDF endpoints
@router.get('/quotes/{quote_id}')
def get_quote_pdf(quote_id: str, print_seal: bool = False, current_user: dict = Depends(require_auth)):
    """Generate quote PDF. print_seal=true adds the company seal (default: no seal)."""
    return service.generate_quote_pdf(quote_id, current_user, print_seal)

# Invoice PDF endpoints
@router.get('/invoices/{invoice_id}')
def get_invoice_pdf(invoice_id: int, print_seal: bool = False, current_user: dict = Depends(require_auth)):
    """Generate invoice PDF. print_seal=true adds the company seal (default: no seal)."""
    return service.generate_invoice_pdf(invoice_id, current_user, print_seal)

@router.get('/invoices/{invoice_id}/conduce')
def get_conduce_pdf(invoice_id: int, print_seal: bool = False, current_user: dict = Depends(require_auth)):
    """Generate conduce (delivery note) PDF for invoice. print_seal=true adds the company seal (default: no seal)."""
    return service.generate_conduce_pdf(invoice_id, current_user, print_seal)
