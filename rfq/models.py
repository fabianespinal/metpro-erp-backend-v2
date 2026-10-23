"""RFQ models. There are NO price fields. extra="forbid" rejects any price a client tries to send (422)."""
from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

DEFAULT_TITLE = "Solicitud de cotización"
# Same company details the other PDFs print in their header.
DEFAULT_BILL_TO = (
    "METPRO SRL\nParque Industrial Disdo\nCalle Central No. 1, Hato Nuevo Palave\n"
    "Tel: (829) 439-8476 | RNC: 131-71683-2"
)


def rfq_label(number) -> str:
    return f"RFQ-{int(number):04d}" if number is not None else "RFQ-S/N"


def _blank_to_none(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class RfqItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: Optional[int] = None
    item: str
    description: Optional[str] = None
    quantity: float
    unit: Optional[str] = None

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

    @field_validator("description", "unit", mode="before")
    @classmethod
    def _b(cls, v):
        return _blank_to_none(v)


class RfqItemOut(BaseModel):
    id: int
    position: int
    product_id: Optional[int] = None
    item: str
    description: Optional[str] = None
    quantity: float
    unit: Optional[str] = None


class RfqIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_id: int
    title: Optional[str] = None
    rfq_date: Optional[date] = None
    bill_to: Optional[str] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    items: List[RfqItemIn]

    @field_validator("title", "bill_to", "payment_terms", "notes", mode="before")
    @classmethod
    def _b(cls, v):
        return _blank_to_none(v)


class RfqOut(BaseModel):
    id: int
    rfq_number: int
    label: str
    supplier_id: int
    vendor_name: str
    vendor_contact: Optional[str] = None
    vendor_email: Optional[str] = None
    vendor_phone: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    title: str
    rfq_date: date
    bill_to: Optional[str] = None
    payment_terms: Optional[str] = None
    notes: Optional[str] = None
    status: Literal["Draft", "Sent", "Converted"]
    created_by: Optional[str] = None
    item_count: int = 0
    items: List[RfqItemOut] = []


class RfqStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["Draft", "Sent"]
