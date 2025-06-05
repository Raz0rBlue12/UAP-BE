from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class NotificationBase(BaseModel):
    message: str = Field(..., description="Content of the notification")

class NotificationCreate(NotificationBase):
    user_id: int = Field(..., description="ID of the user the notification is for")
    # is_read and created_at will be set by the database

class NotificationOut(NotificationBase):
    notification_id: int
    user_id: int
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True
