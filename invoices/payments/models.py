from datetime import date

from pydantic import BaseModel, Field


class PaymentCreate(BaseModel):
    amount: float = Field(gt=0)
    method: str = Field(min_length=1)
    notes: str | None = None
    payment_date: date
