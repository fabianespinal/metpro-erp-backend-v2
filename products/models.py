from pydantic import BaseModel, Field
from typing import Optional

class ProductBase(BaseModel):
    name: str
    description: Optional[str] = None
    unit_price: float
    # Internal unit cost (Product Cost module). Optional, never shown publicly.
    cost: Optional[float] = Field(default=None, ge=0)

class Product(ProductBase):
    id: int
    
    class Config:
        from_attributes = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(ProductBase):
    pass
