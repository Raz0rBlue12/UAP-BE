from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ReviewBase(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5")
    comment: str = Field(..., description="Review comment")

class ReviewCreate(ReviewBase):
    product_id: int = Field(..., description="ID of the product being reviewed")

class ReviewUpdate(ReviewBase):
    pass

class ReviewOut(ReviewBase):
    review_id: int
    product_id: int
    user_id: int
    created_at: datetime

    # Optionally include user and product details for display
    # user: UserOut # Need to import UserOut and fetch user details
    # product: ProductOut # Need to import ProductOut and fetch product details

    class Config:
        from_attributes = True
