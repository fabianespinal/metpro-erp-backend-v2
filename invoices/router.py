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
