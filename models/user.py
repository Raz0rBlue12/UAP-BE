from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Literal, Optional, List

class UserBase(BaseModel):
    username: str
    email: EmailStr
    role: Literal["customer", "seller"]

class UserCreate(UserBase):
    password: str  # plaintext, will be hashed before saving
    role: Literal['customer', 'seller', 'admin']

class UserOut(BaseModel):
    user_id: int
    username: str
    email: EmailStr
    role: Literal['admin', 'customer', 'seller']  # Updated to match actual roles
    created_at: datetime
    is_active: bool

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

class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    bio: Optional[str] = None
    profile_pic: Optional[str] = None

class UserProfileOut(BaseModel):
    profile_id: int
    user_id: int
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    bio: Optional[str] = None
    profile_pic: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
