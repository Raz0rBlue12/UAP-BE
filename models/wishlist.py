from pydantic import BaseModel, Field
from typing import Optional

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
