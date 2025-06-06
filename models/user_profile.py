from pydantic import BaseModel
from typing import Optional

class UserProfile(BaseModel):
    profile_id: int
    user_id: int
    full_name: Optional[str]
    bio: Optional[str]
    profile_pic: Optional[str]

    class Config:
        from_attributes = True
