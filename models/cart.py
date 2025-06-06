from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class ProductImage(BaseModel):
    image_id: int
    image_url: str
    uploaded_at: datetime

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
    product_name: str
    product_description: Optional[str] = None
    product_price: float
    product_stock: int
    product_category: Optional[str] = None
    product_rating: float
    product_images: List[ProductImage] = []

    class Config:
        from_attributes = True
