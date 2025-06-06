from pydantic import BaseModel, Field, validator
from typing import List, Optional, Literal
from datetime import datetime
from decimal import Decimal

class ProductBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: Optional[str] = None
    price: Decimal = Field(..., gt=0)
    stock: int = Field(..., ge=0)
    category: Optional[str] = None
    status: str = Field('pending', description="Status of the product (e.g., pending, approved, rejected)")
    product_type: str = Field('physical', description="Type of product (physical or digital)")

    @validator('status')
    def validate_status(cls, v):
        allowed_statuses = ['pending', 'approved', 'rejected']
        if v not in allowed_statuses:
            raise ValueError(f'Status must be one of {allowed_statuses}')
        return v

    @validator('product_type')
    def validate_product_type(cls, v):
        allowed_types = ['physical', 'digital']
        if v not in allowed_types:
            raise ValueError(f'Product type must be one of {allowed_types}')
        return v

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

    class Config:
        from_attributes = True

class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=150)
    description: Optional[str] = None
    price: Optional[Decimal] = Field(None, gt=0)
    stock: Optional[int] = Field(None, ge=0)
    category: Optional[str] = None
    status: Optional[str] = None
    product_type: Optional[str] = None

    @validator('status', pre=True, always=True)
    def validate_status_optional(cls, v):
        if v is not None:
            allowed_statuses = ['pending', 'approved', 'rejected']
            if v not in allowed_statuses:
                raise ValueError(f'Status must be one of {allowed_statuses}')
        return v

    @validator('product_type', pre=True, always=True)
    def validate_product_type_optional(cls, v):
        if v is not None:
            allowed_types = ['physical', 'digital']
            if v not in allowed_types:
                raise ValueError(f'Product type must be one of {allowed_types}')
        return v
