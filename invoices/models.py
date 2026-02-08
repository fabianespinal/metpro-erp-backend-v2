from pydantic import BaseModel
from typing import Optional

class InvoiceBase(BaseModel):
    quote_id: str
    invoice_number: Optional[str] = None
    notes: Optional[str] = None

class Invoice(BaseModel):
    id: int
    quote_id: str
    invoice_number: str
    invoice_date: str
    client_id: int
    total_amount: float
    status: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True

class InvoiceCreate(InvoiceBase):
    pass

class InvoiceStatusUpdate(BaseModel):
    status: str
