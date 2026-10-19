from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import date


class ExpenseBase(BaseModel):
    # client_id: resolved to clients.company_name (dev frontend).
    # client_name: free text used when client_id is absent (main frontend).
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    date: date
    category: str = Field(min_length=1)
    description: Optional[str] = None
    # Debug B-12: a gasto is a positive, finite amount.
    amount: float = Field(gt=0, allow_inf_nan=False)
    payment_method: Optional[str] = None
    # Project Cost Ledger: projects.id (INTEGER). Empty string or null = no project.
    project_id: Optional[int] = None
    quote_id: Optional[str] = None

    @field_validator("project_id", mode="before")
    @classmethod
    def _blank_project_is_none(cls, v):
        return None if v is None or (isinstance(v, str) and not v.strip()) else v


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    # client_id is intentionally not updatable: it is not a column in expenses.
    date: Optional[date] = None
    category: Optional[str] = Field(default=None, min_length=1)
    client_name: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)
    payment_method: Optional[str] = None
    project_id: Optional[int] = None  # explicit null unlinks the expense from its project
    quote_id: Optional[str] = None

    @field_validator("project_id", mode="before")
    @classmethod
    def _blank_project_is_none(cls, v):
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    @field_validator("date", "category", "amount", mode="before")
    @classmethod
    def _required_columns_not_null(cls, v):
        # Debug B-12: these columns are NOT NULL; an explicit null was a database error (500).
        if v is None:
            raise ValueError("no puede quedar vacío")
        return v


class Expense(ExpenseBase):
    expense_id: int
    created_at: str

    class Config:
        orm_mode = True
