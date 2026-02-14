from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

class ProjectBase(BaseModel):
    client_id: int
    name: str
    description: Optional[str] = None
    status: str = 'planning'
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    estimated_budget: Optional[float] = None
    notes: Optional[str] = None


class Project(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectCreate(BaseModel):
    client_id: int
    name: str
    description: Optional[str] = None
    status: str = 'planning'
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    estimated_budget: Optional[float] = None
    notes: Optional[str] = None


class ProjectUpdate(BaseModel):
    client_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    estimated_budget: Optional[float] = None
    notes: Optional[str] = None