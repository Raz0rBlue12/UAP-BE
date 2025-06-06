from fastapi import APIRouter, HTTPException, status, Depends, Response, UploadFile, File, Request, Query
from typing import List, Optional, Literal
from datetime import datetime
import aiofiles
import os
import tempfile
import magic  # for file type validation
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import re
from pydantic import BaseModel

from models.user import UserOut, UserProfile, UserProfileUpdate, UserProfileOut
from routers.auth import get_current_user
from db.client import get_pg_connection
from config.cloudinary_config import upload_image, delete_image

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# Security configurations
security = HTTPBearer()
ALLOWED_IMAGE_TYPES = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp'
}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
RATE_LIMIT = 100  # requests per minute
RATE_LIMIT_WINDOW = 60  # seconds

# Rate limiting storage
request_counts = {}

def validate_filename(filename: str) -> bool:
    """Validate filename to prevent path traversal and injection attacks"""
    # Remove any directory components
    filename = os.path.basename(filename)
    # Check for valid characters
    return bool(re.match(r'^[a-zA-Z0-9._-]+$', filename))

def check_rate_limit(request: Request) -> bool:
    """Implement rate limiting"""
    client_ip = request.client.host
    current_time = datetime.utcnow().timestamp()
    
    # Clean up old entries
    request_counts[client_ip] = {
        timestamp: count for timestamp, count in request_counts.get(client_ip, {}).items()
        if current_time - timestamp < RATE_LIMIT_WINDOW
    }
    
    # Count requests in the current window
    current_count = sum(request_counts.get(client_ip, {}).values())
    
    if current_count >= RATE_LIMIT:
        return False
    
    # Add current request
    if client_ip not in request_counts:
        request_counts[client_ip] = {}
    request_counts[client_ip][current_time] = request_counts[client_ip].get(current_time, 0) + 1
    
    return True

@router.get("", response_model=List[UserOut])
async def get_users(
    current_user: UserOut = Depends(get_current_user)
):
    """Get all users (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can view all users"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            users = await conn.fetch(
                """
                SELECT user_id, username, email, role, created_at, is_active
                FROM users
                ORDER BY created_at DESC
                """
            )
            return [dict(user) for user in users]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Get user by ID"""
    if current_user.role != "admin" and current_user.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this user"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                user_id
            )
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            return dict(user)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.get("/{user_id}/profile", response_model=UserProfileOut)
async def get_user_profile(
    user_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Get user profile by user ID"""
    if current_user.role != "admin" and current_user.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this profile"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            profile = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE user_id = $1",
                user_id
            )
            if not profile:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Profile not found"
                )
            return dict(profile)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.put("/{user_id}/profile", response_model=UserProfileOut)
async def update_user_profile(
    user_id: int,
    profile_update: UserProfileUpdate,
    current_user: UserOut = Depends(get_current_user)
):
    """Update user profile"""
    if current_user.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this profile"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if profile exists
            profile = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE user_id = $1",
                user_id
            )
            
            if profile:
                # Update existing profile
                updated_profile = await conn.fetchrow(
                    """
                    UPDATE user_profiles 
                    SET 
                        full_name = COALESCE($1, full_name),
                        phone_number = COALESCE($2, phone_number),
                        address = COALESCE($3, address),
                        city = COALESCE($4, city),
                        postal_code = COALESCE($5, postal_code),
                        bio = COALESCE($6, bio),
                        profile_pic = COALESCE($7, profile_pic),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = $8
                    RETURNING *
                    """,
                    profile_update.full_name,
                    profile_update.phone_number,
                    profile_update.address,
                    profile_update.city,
                    profile_update.postal_code,
                    profile_update.bio,
                    profile_update.profile_pic,
                    user_id
                )
            else:
                # Create new profile
                updated_profile = await conn.fetchrow(
                    """
                    INSERT INTO user_profiles 
                    (user_id, full_name, phone_number, address, city, postal_code, bio, profile_pic)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING *
                    """,
                    user_id,
                    profile_update.full_name,
                    profile_update.phone_number,
                    profile_update.address,
                    profile_update.city,
                    profile_update.postal_code,
                    profile_update.bio,
                    profile_update.profile_pic
                )
            
            return dict(updated_profile)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Delete a user (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete users"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if user exists
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                user_id
            )
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            # Prevent deleting the last admin
            if user["role"] == "admin":
                admin_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = true"
                )
                if admin_count <= 1:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot delete the last active admin"
                    )
            
            # Delete user
            await conn.execute(
                "DELETE FROM users WHERE user_id = $1",
                user_id
            )
            return {"message": "User deleted successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

class UserRoleUpdate(BaseModel):
    role: str

class UserStatusUpdate(BaseModel):
    is_active: bool

@router.put("/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: int,
    role_update: UserRoleUpdate,
    current_user: UserOut = Depends(get_current_user)
):
    """Update user role (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update user roles"
        )
    
    # Validate role
    if role_update.role not in ["customer", "seller", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid role. Must be one of: customer, seller, admin"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if user exists
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                user_id
            )
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            # Update user role
            updated_user = await conn.fetchrow(
                """
                UPDATE users 
                SET role = $1
                WHERE user_id = $2
                RETURNING user_id, username, email, role, created_at, is_active
                """,
                role_update.role, user_id
            )
            return dict(updated_user)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.put("/{user_id}/status", response_model=UserOut)
async def update_user_status(
    user_id: int,
    status_update: UserStatusUpdate,
    current_user: UserOut = Depends(get_current_user)
):
    """Update user status (admin only)"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update user status"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if user exists
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE user_id = $1",
                user_id
            )
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            # Prevent deactivating the last admin
            if not status_update.is_active and user["role"] == "admin":
                admin_count = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = true"
                )
                if admin_count <= 1:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot deactivate the last active admin"
                    )
            
            # Update user status
            updated_user = await conn.fetchrow(
                """
                UPDATE users 
                SET is_active = $1
                WHERE user_id = $2
                RETURNING user_id, username, email, role, created_at, is_active
                """,
                status_update.is_active, user_id
            )
            return dict(updated_user)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.post("/{user_id}/profile/upload", response_model=UserProfileOut)
async def upload_profile_picture(
    user_id: int,
    file: UploadFile = File(...),
    current_user: UserOut = Depends(get_current_user)
):
    """Upload profile picture"""
    if current_user.role != "admin" and current_user.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this profile"
        )
    
    # Validate file type
    if not file.content_type.startswith('image/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image"
        )
    
    # Validate file size (max 5MB)
    file_size = 0
    chunk_size = 1024 * 1024  # 1MB chunks
    while chunk := await file.read(chunk_size):
        file_size += len(chunk)
        if file_size > 5 * 1024 * 1024:  # 5MB
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size must be less than 5MB"
            )
    
    # Reset file pointer
    await file.seek(0)
    
    try:
        # Upload to Cloudinary
        upload_result = upload_image(file.file, "profile_pictures")
        
        # Get the image URL from the upload result
        image_url = upload_result.get("url") or upload_result.get("secure_url")
        if not image_url:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get image URL from upload result"
            )
        
        # Update profile in database
        pool = await get_pg_connection()
        try:
            async with pool.acquire() as conn:
                updated_profile = await conn.fetchrow(
                    """
                    UPDATE user_profiles 
                    SET profile_pic = $1, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = $2
                    RETURNING *
                    """,
                    image_url,
                    user_id
                )
                if not updated_profile:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Profile not found"
                    )
                return dict(updated_profile)
        finally:
            await pool.close()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        ) 