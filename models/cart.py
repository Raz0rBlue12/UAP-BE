from pydantic import BaseModel, Field
from typing import Optional

class CartItemBase(BaseModel):
    product_id: int = Field(..., description="ID of the product in the cart")
    quantity: int = Field(..., gt=0, description="Quantity of the product")

class CartItemCreate(CartItemBase):
    pass

class CartItemUpdate(BaseModel):
     quantity: int = Field(..., gt=0, description="New quantity of the product")

class CartItemOut(CartItemBase):
    cart_id: int
    user_id: int
    # Optionally include product details here if needed for display

    class Config:
        from_attributes = True
