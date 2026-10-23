from pydantic import BaseModel
from typing import Any, Dict, List, Optional
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
    itbis_total: Optional[float] = None  # X-04: lets the dashboard show collected money without ITBIS
    amount_paid: float = 0.0
    amount_due: float = 0.0
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    client_name: Optional[str] = None
    created_by_name: Optional[str] = None
    last_status_by: Optional[str] = None  # status history (S1): null when the switch is off
    last_status_at: Optional[datetime] = None
    # Detail view only (GET /invoices/{id}). Lists omit them.
    items: Optional[List[Dict[str, Any]]] = None
    totals: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class InvoiceCreate(InvoiceBase):
    pass


class InvoiceStatusUpdate(BaseModel):
    status: str
