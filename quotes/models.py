from pydantic import BaseModel
from typing import List, Optional

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

class QuoteItemBase(BaseModel):
    product_name: str
    quantity: float
    unit_price: float
    discount_type: str = 'none'
    discount_value: float = 0.0

class QuoteBase(BaseModel):
    client_id: int
    project_name: Optional[str] = None
    notes: Optional[str] = None
    items: List[QuoteItemBase]
    included_charges: IncludedCharges = IncludedCharges()

class QuoteCreate(QuoteBase):
    items: List[QuoteItemBase]

class QuoteUpdate(BaseModel):
    """Update schema - all fields optional, client_id cannot be changed"""
    project_name: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[List[QuoteItemBase]] = None
    included_charges: Optional[IncludedCharges] = None

class StatusUpdate(BaseModel):
    status: str
