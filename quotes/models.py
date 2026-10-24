from pydantic import BaseModel, Field, field_validator, model_validator
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
        # Toggle REQUIRE_CHARGE_NAME (2026-10-22, default OFF): with it on, a blank name is rejected
        # for any enabled charge above 0 (see _require_name below). With it off, legacy behavior.
        from core.switches import switch_on
        if switch_on("REQUIRE_CHARGE_NAME"):
            return v.strip()
        # The UI creates a charge with a blank name; label it instead of rejecting the save.
        return v.strip() or "Cargo adicional"

    @model_validator(mode="after")
    def _require_name(self):
        from core.switches import switch_on
        if switch_on("REQUIRE_CHARGE_NAME"):
            if self.enabled and self.percentage > 0 and not self.name:
                raise ValueError("Cada cargo adicional activo necesita un nombre")
        return self


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
    # A3. None = the client did not send it (older screens). false = counted in totals, never printed to customers.
    print_on_pdf: Optional[bool] = None
    # Medidas: free text unit (Unidad, Ft, M, M2, Ton, Lb, Set ...). None = take the product's unit. Needs PDF_MEDIDAS_ENABLED.
    unit_of_measure: Optional[str] = Field(default=None, max_length=20)


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
    # false = the PDF shows heading, charges and totals only. Totals never change. Needs PDF_PRINT_ITEMS_ENABLED.
    print_items: bool = True


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
    # Engineering estimate quotes: why an admin changed prices, quantities, discounts, charges or tax.
    # Never stored on the quote; written to quote_edit_audit.
    edit_reason: Optional[str] = Field(default=None, max_length=500)
    print_items: Optional[bool] = None


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
    # Audit C2: the edit screen sends engineering_estimate so the preview keeps the quote's own 1.8%.
    quote_type: Optional[Literal["standard", "template", "engineering_estimate"]] = None
