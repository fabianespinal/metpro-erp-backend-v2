from pydantic import BaseModel
from typing import Optional


class ContactBase(BaseModel):
    company_id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None


class ContactRead(ContactBase):
    id: int

    class Config:
        from_attributes = True