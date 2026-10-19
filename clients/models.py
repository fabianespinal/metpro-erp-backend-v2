from pydantic import BaseModel, field_validator
from typing import Optional

class ClientBase(BaseModel):
    company_name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    tax_id: Optional[str] = None
    notes: Optional[str] = None

class Client(ClientBase):
    id: int
    
    class Config:
        from_attributes = True

class ClientCreate(ClientBase):
    pass

class ClientUpdate(ClientBase):
    pass


class ClientInput(ClientBase):
    """POST/PUT body (debug B-12). Responses keep ClientBase so stored rows always serialize.

    - company_name: trimmed, required.
    - optional text fields: trimmed; blank becomes None (B-21: no more '' in tax_id or email).
    """

    @field_validator("company_name", mode="before")
    @classmethod
    def _company_required(cls, v):
        v = (v or "").strip() if isinstance(v, str) or v is None else v
        if not v:
            raise ValueError("El nombre de la empresa es obligatorio")
        return v

    @field_validator("contact_name", "email", "phone", "address", "tax_id", "notes", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v
