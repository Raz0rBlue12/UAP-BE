from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from models.product import ProductOut

class Wishlist(BaseModel):
    wishlist_id: int
    user_id: int
    product_id: int

    class Config:
        from_attributes = True

class WishlistItemBase(BaseModel):
    product_id: int = Field(..., description="ID of the product to add to wishlist")

class WishlistItemCreate(WishlistItemBase):
    pass

class WishlistItemOut(WishlistItemBase):
    wishlist_id: int
    user_id: int
    # Optionally include product details here if needed for display

    class Config:
        from_attributes = True

class WishlistBase(BaseModel):
    product_id: int

class WishlistCreate(WishlistBase):
    pass

class WishlistOut(WishlistBase):
    wishlist_id: int
    user_id: int
    created_at: datetime
    product: ProductOut

    class Config:
        from_attributes = True
