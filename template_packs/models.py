from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, Field


# ----------------------------
# Input
# ----------------------------

class PackItemIn(BaseModel):
    product_id: int = Field(gt=0)
    default_qty: float = Field(default=1, gt=0)
    optional: bool = False
    sort_order: int = 0


class PackCategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sort_order: int = 0
    items: List[PackItemIn] = []


class PackIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    categories: List[PackCategoryIn] = []


# ----------------------------
# Output
# ----------------------------

class PackItemOut(BaseModel):
    id: int
    product_id: int
    product_name: Optional[str] = None
    unit_price: Optional[float] = None
    default_qty: float
    optional: bool
    sort_order: int


class PackCategoryOut(BaseModel):
    id: int
    name: str
    sort_order: int
    items: List[PackItemOut] = []


class PackOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    categories: List[PackCategoryOut] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PackSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    category_count: int
    item_count: int
    updated_at: Optional[datetime] = None
