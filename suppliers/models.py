from typing import Optional

from pydantic import BaseModel, field_validator


class SupplierBase(BaseModel):
    company_name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    notes: Optional[str] = None


class Supplier(SupplierBase):
    id: int
    is_active: bool = True
    is_dummy: bool = False


class SupplierInput(SupplierBase):
    """POST/PUT body. company_name is trimmed and required; blank optional text becomes None."""

    is_active: bool = True

    @field_validator("company_name", mode="before")
    @classmethod
    def _company_required(cls, v):
        v = v.strip() if isinstance(v, str) else v
        if not v:
            raise ValueError("El nombre del suplidor es obligatorio")
        return v

    @field_validator("contact_name", "email", "phone", "address", "tax_id", "notes", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v
