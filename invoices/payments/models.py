from pydantic import BaseModel

class PaymentCreate(BaseModel):
    amount: float
    method: str
    notes: str | None = None
    payment_date: str
