"""Purchase order models. DOP only, no tax. Totals are computed by the backend; a client can never send them."""
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

DEFAULT_TITLE = "Orden de compra"


def po_label(number) -> str:
    return f"PO-{int(number):04d}" if number is not None else "PO-S/N"


def _blank_to_none(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class PoItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # amount is not accepted: the backend computes it
    product_id: Optional[int] = None
    item: str
    description: Optional[str] = None
    quantity: float
    unit: Optional[str] = None
    unit_price: float = 0

    @field_validator("item", mode="before")
    @classmethod
    def _item_required(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v:
            raise ValueError("El artículo es obligatorio")
        return v

    @field_validator("quantity")
    @classmethod
    def _qty(cls, v):
        if not v or v <= 0:
            raise ValueError("La cantidad debe ser mayor que cero")
        return v

    @field_validator("unit_price")
    @classmethod
    def _price(cls, v):
        if v is None or v < 0:
            raise ValueError("El precio no puede ser negativo")
        return v

    @field_validator("description", "unit", mode="before")
    @classmethod
    def _b(cls, v):
        return _blank_to_none(v)


class PoItemOut(BaseModel):
    id: int
    position: int
    product_id: Optional[int] = None
    item: str
    description: Optional[str] = None
    quantity: float
    unit: Optional[str] = None
    unit_price: float
    amount: float


class PoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # subtotal / total are not accepted
    supplier_id: int
    title: Optional[str] = None
    po_date: Optional[date] = None
    bill_to: Optional[str] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    items: List[PoItemIn]

    @field_validator("title", "bill_to", "payment_terms", "notes", mode="before")
    @classmethod
    def _b(cls, v):
        return _blank_to_none(v)


class PoOut(BaseModel):
    id: int
    po_number: int
    label: str
    rfq_id: Optional[int] = None
    rfq_label: Optional[str] = None
    supplier_id: int
    vendor_name: str
    vendor_contact: Optional[str] = None
    vendor_email: Optional[str] = None
    vendor_phone: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    title: str
    po_date: date
    bill_to: Optional[str] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    status: Literal["Draft", "Issued", "Cancelled"]
    subtotal: float
    total: float
    created_by: Optional[str] = None
    item_count: int = 0
    items: List[PoItemOut] = []


class PoStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["Issued", "Cancelled"]
