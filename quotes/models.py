from pydantic import BaseModel, Field
from typing import List, Literal, Optional
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
    # Quoting v1. Accepted and validated now; persisted only after the
    # 2026-10-14_quoting_v1 migration is applied (Phase 5).
    item_type: Literal["product", "service", "custom"] = "product"
    description: Optional[str] = None
    # Optional link to products.id. Not required (existing clients send none).
    # Persisted on create and update from quoting v1 (Phase 6 prerequisite).
    product_id: Optional[int] = None


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
    contact_id: Optional[int] = None


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
    quote_id: str   # ← FIXED
    client_id: int
    contact_id: Optional[int] = None

    project_name: Optional[str]
    notes: Optional[str]

    payment_terms: Optional[str]
    valid_until: Optional[date]

    items: List[QuoteItemBase]
    included_charges: IncludedCharges

    status: Optional[str] = None

    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True


# -----------------------------
# Totals preview (stateless, no DB writes)
# -----------------------------
class TotalsItemIn(BaseModel):
    product_name: str = ""
    quantity: float = Field(default=0, ge=0)
    unit_price: float = Field(default=0, ge=0)
    discount_type: Literal["none", "percentage", "fixed"] = "none"
    discount_value: float = Field(default=0, ge=0)
    item_type: Literal["product", "service", "custom"] = "product"
    description: Optional[str] = None


class TotalsPreviewIn(BaseModel):
    items: List[TotalsItemIn] = []
    included_charges: IncludedCharges = IncludedCharges()
