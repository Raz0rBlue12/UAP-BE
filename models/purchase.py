from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from decimal import Decimal

# Model for shipping address
class ShippingAddress(BaseModel):
    street: str = Field(..., description="Street address")
    city: str = Field(..., description="City")
    state: str = Field(..., description="State/Province")
    postal_code: str = Field(..., description="Postal/ZIP code")
    country: str = Field(..., description="Country")

# Model for a single item when creating an order
class OrderItemCreate(BaseModel):
    product_id: int = Field(..., description="ID of the product")
    quantity: int = Field(..., gt=0, description="Quantity of the product")

# Model for creating a new order (contains multiple items)
class OrderCreate(BaseModel):
    items: List[OrderItemCreate] = Field(..., min_items=1, description="List of items in the order")
    shipping_address: Optional[ShippingAddress] = Field(None, description="Shipping address for the entire order (optional for digital products)")
    payment_method: str = Field(..., description="Payment method for the order")
    # total_amount is calculated on the backend

# Model for a single item within an order output
class OrderItemOut(BaseModel):
    order_item_id: int = Field(..., alias='purchase_id') # Alias to match old column name if needed initially
    order_id: int
    product_id: int
    quantity: int
    total_price: Decimal
    # Assuming we want product details included in the output
    product_name: str
    product_image: Optional[str] = None # Assuming product_images table is joined

    class Config:
        from_attributes = True
        populate_by_name = True # Allow population by field name or alias

# Model for the complete order output
class OrderOut(BaseModel):
    order_id: int
    user_id: int
    shipping_address: Optional[ShippingAddress] = None
    payment_method: str
    total_amount: Decimal
    status: str
    created_at: datetime
    updated_at: datetime
    tracking_number: Optional[str] = None
    estimated_delivery: Optional[datetime] = None
    items: List[OrderItemOut] = [] # List of items in this order

    class Config:
        from_attributes = True

# Model for updating an order (e.g., status update)
class OrderUpdate(BaseModel):
    status: Optional[str] = Field(None, description="Status of the order (e.g., pending, shipped)")
    tracking_number: Optional[str] = Field(None, description="Tracking number for the shipment")
    estimated_delivery: Optional[datetime] = Field(None, description="Estimated delivery date")

    class Config:
        from_attributes = True
