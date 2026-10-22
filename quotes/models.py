from pydantic import BaseModel, Field, field_validator
from typing import List, Literal, Optional
from datetime import datetime, date


# -----------------------------
# Included Charges
# -----------------------------
class DynamicCharge(BaseModel):
    """User-defined charge, percentage of items_after_discount (like the static five)."""
    id: Optional[str] = None
    name: str = Field(default="", max_length=60)
    enabled: bool = True
    percentage: float = Field(default=0.0, ge=0, le=100)

    @field_validator("name")
    @classmethod
    def _default_blank_name(cls, v: str) -> str:
        # The UI creates a charge with a blank name; label it instead of rejecting the save.
        return v.strip() or "Cargo adicional"


class IncludedCharges(BaseModel):
    supervision: bool = True
    supervision_percentage: float = Field(default=10.0, ge=0, le=100)

    admin: bool = True
    admin_percentage: float = Field(default=4.0, ge=0, le=100)

    insurance: bool = True
    insurance_percentage: float = Field(default=1.0, ge=0, le=100)

    transport: bool = True
    transport_percentage: float = Field(default=3.0, ge=0, le=100)

    contingency: bool = True
    contingency_percentage: float = Field(default=3.0, ge=0, le=100)

    # Up to 3 user-defined charges. Optional: legacy payloads and rows omit it.
    dynamic_charges: List[DynamicCharge] = Field(default_factory=list, max_length=3)


# -----------------------------
# Quote Items
# -----------------------------
class QuoteItemBase(BaseModel):
    product_name: str
    quantity: float = Field(ge=0)
    unit_price: float = Field(ge=0)
    discount_type: Literal["none", "percentage", "fixed"] = "none"
    # percentage: 0-100 of the line. fixed: currency amount for the whole line,
    # at most quantity * unit_price (checked in quotes.service).
    discount_value: float = Field(default=0.0, ge=0)
    # Quoting v1. Accepted and validated now; persisted only after the
    # 2026-10-14_quoting_v1 migration is applied (Phase 5).
    item_type: Literal["product", "service", "custom"] = "product"
    description: Optional[str] = None
    # Optional link to products.id. Not required (existing clients send none).
    # Persisted on create and update from quoting v1 (Phase 6 prerequisite).
    product_id: Optional[int] = None
    # Template-pack category name. Printed as a section heading on the PDFs.
    category: Optional[str] = Field(default=None, max_length=120)


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
    # A1: code from tax_types. None = the default type. Unknown or inactive codes are rejected (400).
    tax_type_code: Optional[str] = Field(default=None, max_length=40)


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
    # A1: changes the snapshot. Draft only (the whole update is Draft-only).
    tax_type_code: Optional[str] = Field(default=None, max_length=40)


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


class CostPreviewIn(BaseModel):
    """Unsaved lines for the estimated-cost preview (Product Cost module). Nothing is stored."""
    items: List[QuoteItemBase] = []
    included_charges: IncludedCharges = IncludedCharges()


class TotalsPreviewIn(BaseModel):
    items: List[TotalsItemIn] = []
    included_charges: IncludedCharges = IncludedCharges()
    tax_type_code: Optional[str] = Field(default=None, max_length=40)
