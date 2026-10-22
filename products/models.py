from pydantic import BaseModel, Field
from typing import Optional

class ProductBase(BaseModel):
    name: str
    description: Optional[str] = None
    # Finite and non-negative: NaN or Infinity would break every product listing (debug B-01).
    unit_price: float = Field(ge=0, allow_inf_nan=False)
    # Internal unit cost (Product Cost module). Optional, never shown publicly.
    cost: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    # B3 dimensions (estimation foundation). Optional, stored as entered, nothing derived.
    length: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    width: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    height: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    thickness: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    area: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    volume: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    unit_of_measure: Optional[str] = Field(default=None, min_length=1, max_length=20)

DIMENSION_FIELDS = ("length", "width", "height", "thickness", "area", "volume", "unit_of_measure")

class Product(ProductBase):
    id: int
    
    class Config:
        from_attributes = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(ProductBase):
    pass
