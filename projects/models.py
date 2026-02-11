from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

class ProjectBase(BaseModel):
    client_id: int
    name: str
    description: Optional[str] = None
    status: str = 'planning'
    start_date: date
    end_date: Optional[date] = None
    estimated_budget: Optional[float] = None
    notes: Optional[str] = None

class Project(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(ProjectBase):
    pass