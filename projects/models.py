from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import date, datetime

# Allowed statuses (MUST match Supabase constraint)
ALLOWED_STATUSES = {
    'pending',
    'planning',
    'in_progress',
    'completed',
    'on_hold',
    'cancelled',
}

class ProjectBase(BaseModel):
    client_id: int
    name: str
    description: Optional[str] = None
    status: str = 'planning'
    start_date: date  # NOT NULL in Supabase
    end_date: Optional[date] = None
    estimated_budget: Optional[float] = None
    notes: Optional[str] = None
    job_site_address: Optional[str] = None

    # Normalize empty strings → None
    @field_validator('description', 'notes', 'job_site_address', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v

    # Normalize and validate status
    @field_validator('status', mode='before')
    @classmethod
    def validate_status(cls, v):
        if v is None:
            return None

        v = v.strip().lower()

        # Normalize "in progress" → "in_progress"
        if v == "in progress":
            v = "in_progress"

        if v not in ALLOWED_STATUSES:
            raise ValueError(f"El estado debe ser uno de: {', '.join(sorted(ALLOWED_STATUSES))}")

        return v


class Project(ProjectBase):
    id: int
    created_at: datetime
    updated_at: datetime
    # Derived / joined (read only)
    project_number: Optional[str] = None      # P-0001
    client_name: Optional[str] = None
    quote_id: Optional[str] = None
    quote_number: Optional[int] = None
    quote_label: Optional[str] = None         # Q-10002
    invoice_id: Optional[int] = None
    invoice_number: Optional[str] = None      # F-10002

    class Config:
        from_attributes = True


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    client_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    estimated_budget: Optional[float] = None
    notes: Optional[str] = None
    job_site_address: Optional[str] = None

    # Normalize empty strings → None
    @field_validator('description', 'notes', 'job_site_address', mode='before')
    @classmethod
    def empty_str_to_none(cls, v):
        if v == "":
            return None
        return v

    # Prevent empty name
    @field_validator('name', mode='before')
    @classmethod
    def empty_name_check(cls, v):
        if v == "":
            raise ValueError("El nombre no puede estar vacío")
        return v

    # Normalize and validate status
    @field_validator('status', mode='before')
    @classmethod
    def validate_status(cls, v):
        if v is None:
            return None

        v = v.strip().lower()

        # Normalize "in progress" → "in_progress"
        if v == "in progress":
            v = "in_progress"

        if v not in ALLOWED_STATUSES:
            raise ValueError(f"El estado debe ser uno de: {', '.join(sorted(ALLOWED_STATUSES))}")

        return v
