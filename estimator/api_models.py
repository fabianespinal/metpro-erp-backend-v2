from datetime import date
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProfilePick(BaseModel):
    columnas: str
    frontales: str
    tijerillas: str
    frenado: str


class Override(BaseModel):
    row: int
    unit_price: Optional[float] = Field(default=None, ge=0)
    quantity: Optional[float] = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=500)


class EstimateRequest(BaseModel):
    ancho: float
    largo: float
    altura_laterales: float
    altura_techado_lateral: float
    distancia_ejes: float
    columnas_frontales: float
    perfiles: ProfilePick
    overrides: List[Override] = []


class GenerateRequest(EstimateRequest):
    idempotency_key: UUID
    client_id: int
    contact_id: int
    project_name: Optional[str] = Field(default=None, max_length=200)
    notes: Optional[str] = None
    payment_terms: Optional[str] = None
    valid_until: Optional[date] = None


class ParityRequest(BaseModel):
    # workbook cell -> value the admin typed (E42, C93, F78, F122 ...). Not stored.
    values: Dict[str, float]
