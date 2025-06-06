from pydantic import BaseModel
from datetime import datetime

class MessageBase(BaseModel):
    content: str

class MessageCreate(MessageBase):
    receiver_id: int

class MessageOut(MessageBase):
    message_id: int
    sender_id: int
    receiver_id: int
    sent_at: datetime
    is_read: bool = False

    class Config:
        from_attributes = True
