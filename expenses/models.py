from pydantic import BaseModel
from typing import Optional
from datetime import date

class ExpenseBase(BaseModel):
    client_id: Optional[int] = None
    date: date
    category: str
    description: Optional[str] = None
    amount: float
    payment_method: Optional[str] = None
    project_id: Optional[str] = None
    quote_id: Optional[str] = None

class ExpenseCreate(ExpenseBase):
    pass

class ExpenseUpdate(BaseModel):
    date: Optional[date] = None
    category: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    payment_method: Optional[str] = None
    project_id: Optional[str] = None
    quote_id: Optional[str] = None

class Expense(ExpenseBase):
    expense_id: int
    created_at: str

    class Config:
        orm_mode = True