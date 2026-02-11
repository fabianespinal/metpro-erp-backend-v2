from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class InvoiceBase(BaseModel):
    quote_id: str
    invoice_number: Optional[str] = None
    notes: Optional[str] = None

class Invoice(BaseModel):
    id: int
    quote_id: str
    invoice_number: str
    invoice_date: datetime
    client_id: int
    total_amount: float
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class InvoiceCreate(InvoiceBase):
    pass

class InvoiceStatusUpdate(BaseModel):
    status: str