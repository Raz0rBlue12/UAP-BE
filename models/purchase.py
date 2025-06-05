from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal

class PurchaseItem(BaseModel):
    product_id: int
    quantity: int
    price: Decimal
    product_name: str
    product_image: Optional[str] = None

class PurchaseCreate(BaseModel):
    items: List[PurchaseItem]
    shipping_address: str
    payment_method: str
    total_amount: Decimal

class PurchaseOut(BaseModel):
    purchase_id: int
    user_id: int
    items: List[PurchaseItem]
    shipping_address: str
    payment_method: str
    total_amount: Decimal
    status: str
    created_at: datetime
    updated_at: datetime
    tracking_number: Optional[str] = None
    estimated_delivery: Optional[datetime] = None

    class Config:
        from_attributes = True

class PurchaseUpdate(BaseModel):
    status: Optional[str] = None
    tracking_number: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
