from fastapi import APIRouter, HTTPException, status, Depends, Response, UploadFile, File, Request, Query
from typing import List, Optional, Literal
from datetime import datetime
import aiofiles
import os
import tempfile
import magic  # for file type validation
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import re

from models.user import UserOut, UserProfile
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

@router.get("/", response_model=List[UserOut])
async def get_users(
    request: Request,
    skip: int = 0,
    limit: int = 10,
    current_user = Depends(get_current_user)
):
    """Get all users (admin only)"""
    # Rate limiting
    if not check_rate_limit(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests"
        )
    
    # Input validation
    if skip < 0 or limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid pagination parameters"
        )
    
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view all users"
        )
    
    conn = await get_pg_connection()
    try:
        users = await conn.fetch(
            """
            SELECT user_id, username, email, role, created_at
            FROM users
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit, skip
        )
        return [dict(user) for user in users]
    finally:
        await conn.close()

@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    request: Request,
    user_id: int,
    current_user = Depends(get_current_user)
):
    """Get user by ID"""
    # Rate limiting
    if not check_rate_limit(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests"
        )
    
    # Input validation
    if user_id < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID"
        )
    
    if current_user["role"] != "admin" and current_user["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this user"
        )
    
    conn = await get_pg_connection()
    try:
        user = await conn.fetchrow(
            """
            SELECT user_id, username, email, role, created_at
            FROM users
            WHERE user_id = $1
            """,
            user_id
        )
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        return dict(user)
    finally:
        await conn.close()

@router.get("/{user_id}/profile", response_model=UserProfile)
async def get_user_profile(
    user_id: int,
    current_user = Depends(get_current_user)
):
    """Get user profile"""
    # Users can only view their own profile unless they're admin
    if current_user["role"] != "admin" and current_user["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this profile"
        )
    
    conn = await get_pg_connection()
    try:
        profile = await conn.fetchrow(
            """
            SELECT profile_id, user_id, full_name, bio, profile_pic
            FROM user_profiles
            WHERE user_id = $1
            """,
            user_id
        )
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )
        return dict(profile)
    finally:
        await conn.close()

@router.put("/{user_id}/profile", response_model=UserProfile)
async def update_user_profile(
    user_id: int,
    profile: UserProfile,
    current_user = Depends(get_current_user)
):
    """Update user profile"""
    # Users can only update their own profile unless they're admin
    if current_user["role"] != "admin" and current_user["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this profile"
        )
    
    conn = await get_pg_connection()
    try:
        async with conn.transaction():
            # Check if profile exists
            existing_profile = await conn.fetchrow(
                "SELECT profile_id FROM user_profiles WHERE user_id = $1",
                user_id
            )
            
            if existing_profile:
                # Update existing profile
                updated_profile = await conn.fetchrow(
                    """
                    UPDATE user_profiles
                    SET full_name = $1, bio = $2, profile_pic = $3
                    WHERE user_id = $4
                    RETURNING profile_id, user_id, full_name, bio, profile_pic
                    """,
                    profile.full_name, profile.bio, profile.profile_pic, user_id
                )
            else:
                # Create new profile
                updated_profile = await conn.fetchrow(
                    """
                    INSERT INTO user_profiles (user_id, full_name, bio, profile_pic)
                    VALUES ($1, $2, $3, $4)
                    RETURNING profile_id, user_id, full_name, bio, profile_pic
                    """,
                    user_id, profile.full_name, profile.bio, profile.profile_pic
                )
            
            return dict(updated_profile)
    finally:
        await conn.close()

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    request: Request,
    user_id: int,
    current_user = Depends(get_current_user)
):
    """Delete user (admin only)"""
    # Rate limiting
    if not check_rate_limit(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests"
        )

    # Input validation
    if user_id < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID"
        )

    # Authorization: Only admin can delete users, and cannot delete themselves
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete users"
        )
    if current_user["user_id"] == user_id:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account"
        )

    conn = await get_pg_connection()
    try:
        async with conn.transaction():
            # Check if user exists
            existing_user = await conn.fetchrow(
                "SELECT user_id FROM users WHERE user_id = $1",
                user_id
            )
            if not existing_user:
                 raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            # Delete user (ON DELETE CASCADE handles related data like profile, cart, wishlist, etc.)
            result = await conn.execute(
                "DELETE FROM users WHERE user_id = $1",
                user_id
            )

            if result != "DELETE 1":
                 raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to delete user"
                )

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await conn.close()

@router.put("/{user_id}/role", response_model=UserOut)
async def update_user_role(
    request: Request,
    user_id: int,
    new_role: Literal["customer", "seller", "admin"],
    current_user = Depends(get_current_user)
):
    """Update user role (admin only)"""
    # Rate limiting
    if not check_rate_limit(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests"
        )

    # Input validation
    if user_id < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID"
        )

    # Authorization: Only admin can update roles, and cannot change their own role
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update user roles"
        )
    if current_user["user_id"] == user_id:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role"
        )

    conn = await get_pg_connection()
    try:
        async with conn.transaction():
            # Check if user exists
            existing_user = await conn.fetchrow(
                "SELECT user_id FROM users WHERE user_id = $1",
                user_id
            )
            if not existing_user:
                 raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            # Update the user's role
            updated_user = await conn.fetchrow(
                """
                UPDATE users
                SET role = $1
                WHERE user_id = $2
                RETURNING user_id, username, email, role, created_at, is_active
                """,
                new_role,
                user_id
            )

            if not updated_user:
                 raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update user role"
                )

            # Note: Assuming UserOut model includes is_active after db migration
            return dict(updated_user)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await conn.close()

@router.put("/{user_id}/status", response_model=UserOut)
async def update_user_status(
    request: Request,
    user_id: int,
    is_active: bool = Query(..., description="Set user active status (true/false)"),
    current_user = Depends(get_current_user)
):
    """Activate or deactivate user (admin only)"""
    # Rate limiting
    if not check_rate_limit(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests"
        )

    # Input validation
    if user_id < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID"
        )

    # Authorization: Only admin can update status, and cannot change their own status
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update user status"
        )
    if current_user["user_id"] == user_id and not is_active:
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account"
        )

    conn = await get_pg_connection()
    try:
        async with conn.transaction():
            # Check if user exists
            existing_user = await conn.fetchrow(
                "SELECT user_id FROM users WHERE user_id = $1",
                user_id
            )
            if not existing_user:
                 raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )

            # Update the user's active status
            updated_user = await conn.fetchrow(
                """
                UPDATE users
                SET is_active = $1
                WHERE user_id = $2
                RETURNING user_id, username, email, role, created_at, is_active
                """,
                is_active,
                user_id
            )

            if not updated_user:
                 raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to update user status"
                )

            # Note: Assuming UserOut model includes is_active after db migration
            return dict(updated_user)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await conn.close()

@router.post("/{user_id}/profile/upload", response_model=UserProfile)
async def upload_profile_picture(
    request: Request,
    user_id: int,
    file: UploadFile = File(...),
    current_user = Depends(get_current_user)
):
    """Upload profile picture"""
    # Rate limiting
    if not check_rate_limit(request):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests"
        )
    
    # Input validation
    if user_id < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user ID"
        )
    
    if not validate_filename(file.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename"
        )
    
    # Authorization check
    if current_user["role"] != "admin" and current_user["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to upload profile picture"
        )
    
    # File validation
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large"
        )
    
    # Check file type using python-magic
    file_type = magic.from_buffer(content, mime=True)
    if file_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file type"
        )
    
    conn = await get_pg_connection()
    try:
        async with conn.transaction():
            # Get current profile
            profile = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE user_id = $1",
                user_id
            )
            
            # Save file temporarily with secure permissions
            temp_fd, temp_path = tempfile.mkstemp(suffix=ALLOWED_IMAGE_TYPES[file_type])
            try:
                with os.fdopen(temp_fd, 'wb') as temp_file:
                    temp_file.write(content)
                os.chmod(temp_path, 0o600)  # Secure file permissions
                
                # Upload to Cloudinary
                upload_result = upload_image(
                    temp_path,
                    folder="profiles",
                    resource_type="image"
                )
                
                # If there's an existing profile picture, delete it from Cloudinary
                if profile and profile["profile_pic"]:
                    try:
                        public_id = profile["profile_pic"].split("/")[-1].split(".")[0]
                        delete_image(public_id)
                    except Exception as e:
                        print(f"Error deleting old profile picture: {str(e)}")
                
                # Update or create profile
                if profile:
                    updated_profile = await conn.fetchrow(
                        """
                        UPDATE user_profiles
                        SET profile_pic = $1
                        WHERE user_id = $2
                        RETURNING profile_id, user_id, full_name, bio, profile_pic
                        """,
                        upload_result["url"], user_id
                    )
                else:
                    updated_profile = await conn.fetchrow(
                        """
                        INSERT INTO user_profiles (user_id, profile_pic)
                        VALUES ($1, $2)
                        RETURNING profile_id, user_id, full_name, bio, profile_pic
                        """,
                        user_id, upload_result["url"]
                    )
                
                return dict(updated_profile)
            
            finally:
                # Secure cleanup of temporary file
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    print(f"Error deleting temporary file: {str(e)}")
    
    finally:
        await conn.close() 