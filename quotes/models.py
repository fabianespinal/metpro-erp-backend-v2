from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date


# -----------------------------
# Included Charges
# -----------------------------
class IncludedCharges(BaseModel):
    supervision: bool = True
    supervision_percentage: float = 10.0

    admin: bool = True
    admin_percentage: float = 4.0

    insurance: bool = True
    insurance_percentage: float = 1.0

    transport: bool = True
    transport_percentage: float = 3.0

    contingency: bool = True
    contingency_percentage: float = 3.0


# -----------------------------
# Quote Items
# -----------------------------
class QuoteItemBase(BaseModel):
    product_name: str
    quantity: float
    unit_price: float
    discount_type: str = "none"
    discount_value: float = 0.0


# -----------------------------
# Base Quote Schema
# -----------------------------
class QuoteBase(BaseModel):
    client_id: int
    project_name: Optional[str] = None
    notes: Optional[str] = None

    # NEW FIELDS
    payment_terms: Optional[str] = None
    valid_until: Optional[date] = None

    items: List[QuoteItemBase]
    included_charges: IncludedCharges = IncludedCharges()


# -----------------------------
# Create Quote
# -----------------------------
class QuoteCreate(QuoteBase):
    items: List[QuoteItemBase]


# -----------------------------
# Update Quote
# -----------------------------
class QuoteUpdate(BaseModel):
    project_name: Optional[str] = None
    notes: Optional[str] = None

    # NEW FIELDS
    payment_terms: Optional[str] = None
    valid_until: Optional[date] = None

    items: Optional[List[QuoteItemBase]] = None
    included_charges: Optional[IncludedCharges] = None


# -----------------------------
# Status Update
# -----------------------------
class StatusUpdate(BaseModel):
    status: str


# -----------------------------
# FULL RESPONSE MODEL (IMPORTANT)
# -----------------------------
class QuoteResponse(BaseModel):
    id: int
    quote_number: str
    client_id: int

    project_name: Optional[str]
    notes: Optional[str]

    # NEW FIELDS
    payment_terms: Optional[str]
    valid_until: Optional[date]

    items: List[QuoteItemBase]
    included_charges: IncludedCharges

    status: Optional[str] = None

    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True
