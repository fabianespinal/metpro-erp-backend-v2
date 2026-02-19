from fastapi import APIRouter, Depends
from .models import PaymentCreate
from .service import create_payment
from backend.database import get_db

router = APIRouter(prefix="/payments", tags=["payments"])

@router.post("/{invoice_id}")
def add_payment(invoice_id: int, data: PaymentCreate, conn=Depends(get_db)):
    payment_id = create_payment(conn, invoice_id, data)
    return {"payment_id": payment_id}
