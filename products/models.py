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
    # B3 dimensions (estimation foundation). Optional, stored as entered, nothing derived.
    # unit_of_measure above is the Medidas label and is NOT a dimension field (it works with its own switch).
    length: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    width: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    height: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    thickness: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    area: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)
    volume: Optional[float] = Field(default=None, ge=0, allow_inf_nan=False)

DIMENSION_FIELDS = ("length", "width", "height", "thickness", "area", "volume")

class Product(ProductBase):
    id: int
    
    class Config:
        from_attributes = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(ProductBase):
    pass
