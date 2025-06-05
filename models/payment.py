from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class Payment(BaseModel):
    payment_id: int
    user_id: int
    purchase_id: Optional[int]
    method: str
    amount: float
    status: str
    paid_at: datetime

    class Config:
        orm_mode = True
