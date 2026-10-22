from typing import List, Literal, Optional
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ----------------------------
# Input
# ----------------------------

MAX_PACK_CHARGES = 3


class PackItemIn(BaseModel):
    product_id: int = Field(gt=0)
    default_qty: float = Field(default=1, gt=0)
    optional: bool = False
    sort_order: int = 0
    # None = use the catalog price (products.unit_price).
    pack_price_override: Optional[float] = Field(default=None, ge=0)
    # A3. None = not sent (older screens). false = counted in totals, never printed to customers.
    print_on_pdf: Optional[bool] = None


class PackCategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0
    items: List[PackItemIn] = []


class PackChargeIn(BaseModel):
    """Copied into the quote's included_charges.dynamic_charges when a quote starts from the pack.
    Percentage of items after discount, same rule as quote dynamic charges."""
    name: str = Field(min_length=1, max_length=60)
    type: Literal["percentage"] = "percentage"
    value: float = Field(ge=0, le=100)
    enabled_by_default: bool = True
    sort_order: int = 0

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Charge name is required")
        return v


class PackIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    categories: List[PackCategoryIn] = []
    # Omitted = no charges. On PUT, omitted clears the pack's charges (full replace, like categories).
    charges: List[PackChargeIn] = Field(default_factory=list, max_length=MAX_PACK_CHARGES)


# ----------------------------
# Output
# ----------------------------

class PackItemOut(BaseModel):
    id: int
    product_id: int
    product_name: Optional[str] = None
    # Effective price for quoting: pack_price_override when set, else catalog_price.
    # Existing clients (take-off) read this field, so they pick up overrides unchanged.
    unit_price: Optional[float] = None
    catalog_price: Optional[float] = None
    pack_price_override: Optional[float] = None
    default_qty: float
    optional: bool
    sort_order: int
    print_on_pdf: bool = True


class PackChargeOut(BaseModel):
    id: int
    name: str
    type: Literal["percentage"]
    value: float
    enabled_by_default: bool
    sort_order: int


class PackCategoryOut(BaseModel):
    id: int
    name: str
    sort_order: int
    items: List[PackItemOut] = []


class PackOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    categories: List[PackCategoryOut] = []
    charges: List[PackChargeOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PackSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    category_count: int
    item_count: int
    updated_at: Optional[datetime] = None
