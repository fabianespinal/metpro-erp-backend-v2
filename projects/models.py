from pydantic import BaseModel
from typing import Optional

class ProjectBase(BaseModel):
    client_id: int
    name: str
    description: Optional[str] = None
    status: str = 'planning'
    start_date: str  # ISO date string
    end_date: Optional[str] = None
    estimated_budget: Optional[float] = None
    notes: Optional[str] = None

class Project(ProjectBase):
    id: int
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(ProjectBase):
    pass
