from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Literal, Optional

class UserBase(BaseModel):
    username: str
    email: EmailStr
    role: Literal["customer", "seller"]

class UserCreate(UserBase):
    password: str  # plaintext, will be hashed before saving

class UserOut(BaseModel):
    user_id: int
    username: str
    email: EmailStr
    role: Literal['admin', 'customer', 'staff']  # Sesuaikan dengan enum yang Anda gunakan
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class UserProfile(BaseModel):
    profile_id: int
    user_id: int
    full_name: Optional[str] = None
    bio: Optional[str] = None
    profile_pic: Optional[str] = None

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
