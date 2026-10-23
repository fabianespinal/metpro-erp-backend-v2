from pydantic import BaseModel, Field
from typing import Optional

class ProductBase(BaseModel):
    name: str
    description: Optional[str] = None
    # Finite and non-negative: NaN or Infinity would break every product listing (debug B-01).
    unit_price: float = Field(ge=0, allow_inf_nan=False)
    # Internal unit cost (Product Cost module). Optional, never shown publicly.
    cost: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    # Medidas: free text (Unidad, Ft, M, M2, Ton, Lb, Set ...). Stored only when PDF_MEDIDAS_ENABLED is on.
    unit_of_measure: Optional[str] = Field(default=None, max_length=20)

class Product(ProductBase):
    id: int
    
    class Config:
        from_attributes = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(ProductBase):
    pass
