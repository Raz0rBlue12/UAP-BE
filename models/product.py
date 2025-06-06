from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime

class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    stock: int = Field(..., ge=0)
    category: Optional[str] = None

class ProductCreate(ProductBase):
    # seller_id will be inferred from the authenticated user
    pass

class ProductImage(BaseModel):
    image_id: int
    image_url: str
    uploaded_at: datetime

class ProductOut(BaseModel):
    product_id: int
    seller_id: int
    name: str
    description: str
    price: float
    stock: int
    category: str
    rating: float
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    images: List[ProductImage] = []

class ProductUpdate(ProductBase):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=0)
    category: Optional[str] = None
    # Cannot update seller_id or rating directly
