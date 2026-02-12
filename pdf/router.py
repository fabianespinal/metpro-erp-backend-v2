from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from .models import Invoice, InvoiceCreate, InvoiceStatusUpdate
from . import service
from pdf import service as pdf_service
from auth.service import verify_token

router = APIRouter(prefix='/invoices', tags=['invoices'])

@router.post('/', response_model=Invoice)
def create_invoice(invoice: InvoiceCreate, current_user: dict = Depends(verify_token)):
    """Create invoice from approved quote"""
    result = service.create_invoice_from_quote(invoice.quote_id, invoice.notes)
    return Invoice(**result)

@router.get('/', response_model=List[Invoice])
def get_invoices(
    client_id: Optional[int] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(verify_token)
):
    """Get all invoices with optional filters"""
    invoices = service.get_all_invoices(client_id, status)
    return [Invoice(**inv) for inv in invoices]

@router.get('/{invoice_id}', response_model=Invoice)
def get_invoice(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Get single invoice with items and calculations"""
    result = service.get_invoice_by_id(invoice_id)
    return Invoice(**result)

@router.get('/number/{invoice_number}', response_model=Invoice)
def get_invoice_by_number(invoice_number: str, current_user: dict = Depends(verify_token)):
    """Get invoice by invoice number"""
    result = service.get_invoice_by_number(invoice_number)
    return Invoice(**result)

@router.patch('/{invoice_id}/status', response_model=Invoice)
def update_invoice_status(
    invoice_id: int,
    status_update: InvoiceStatusUpdate,
    current_user: dict = Depends(verify_token)
):
    """Update invoice status"""
    result = service.update_invoice_status(invoice_id, status_update.status)
    return Invoice(**result)

@router.get('/{invoice_id}/pdf')
def get_invoice_pdf(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Generate invoice PDF"""
    return pdf_service.generate_invoice_pdf(invoice_id)

@router.get('/{invoice_id}/conduce/pdf')
def get_conduce_pdf(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Generate conduce (delivery note) PDF for invoice"""
    return pdf_service.generate_conduce_pdf(invoice_id)

@router.delete('/{invoice_id}')
def delete_invoice(invoice_id: int, current_user: dict = Depends(verify_token)):
    """Delete invoice and revert quote status"""
    return service.delete_invoice(invoice_id)