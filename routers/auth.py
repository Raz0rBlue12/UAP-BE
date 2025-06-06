from fastapi import APIRouter, HTTPException, status, Depends, Request, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
import jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import os
import re
from dotenv import load_dotenv
import time
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from db.client import supabase, get_pg_connection
from services.email_service import send_reset_password_email
from utils.rate_limiter import RateLimiter
from jwt.exceptions import InvalidTokenError

from models.user import UserCreate, UserOut, UserLogin, Token, TokenData

load_dotenv()

router = APIRouter(
    prefix="/auth",
    tags=["Auth"]
)

# Security Configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY")  # Change this in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
MAX_LOGIN_ATTEMPTS = 5
LOGIN_TIMEOUT_MINUTES = 15
PASSWORD_MIN_LENGTH = 8
TOKEN_BLACKLIST: Dict[str, float] = {}
RESET_TOKEN_EXPIRE_MINUTES = 60

# Password hashing configuration
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12  # Increased rounds for better security
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

# Rate limiting storage
# login_attempts: Dict[str, Dict[str, int]] = {}

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

def is_password_strong(password: str) -> bool:
    """
    Check if password meets security requirements:
    - At least 8 characters
    - Contains uppercase and lowercase letters
    - Contains numbers
    - Contains special characters
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return False
    
    if not re.search(r"[A-Z]", password):
        return False
    
    if not re.search(r"[a-z]", password):
        return False
    
    if not re.search(r"\d", password):
        return False
    
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password):
        return False
    
    return True

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),  # Issued at time
        "jti": str(time.time())    # Unique token ID
    })
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# def check_rate_limit(email: str) -> bool:
#     """Check if user has exceeded login attempts"""
#     if email not in login_attempts:
#         login_attempts[email] = {"attempts": 0, "last_attempt": time.time()}
#         return True
#     
#     current_time = time.time()
#     last_attempt = login_attempts[email]["last_attempt"]
#     
#     # Reset attempts if timeout period has passed
#     if current_time - last_attempt > LOGIN_TIMEOUT_MINUTES * 60:
#         login_attempts[email] = {"attempts": 0, "last_attempt": current_time}
#         return True
#     
#     # Check if max attempts reached
#     if login_attempts[email]["attempts"] >= MAX_LOGIN_ATTEMPTS:
#         return False
#     
#     login_attempts[email]["attempts"] += 1
#     login_attempts[email]["last_attempt"] = current_time
#     return True

async def get_current_user(token: str = Depends(oauth2_scheme)) -> UserOut:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(email=email)
    except InvalidTokenError:
        raise credentials_exception
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT * FROM users WHERE email = $1",
                token_data.email
            )
            if user is None:
                raise credentials_exception
            return UserOut(**dict(user))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.post("/register", response_model=UserOut)
async def register_user(user: UserCreate):
    """Register a new user"""
    # Prevent direct admin registration
    if user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot register as admin directly"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if username or email already exists
            existing_user = await conn.fetchrow(
                "SELECT username, email FROM users WHERE username = $1 OR email = $2",
                user.username, user.email
            )
            if existing_user:
                if existing_user['username'] == user.username:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Username already registered"
                    )
                if existing_user['email'] == user.email:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email already registered"
                    )

            # Hash the password
            hashed_password = pwd_context.hash(user.password)

            # Create user
            new_user = await conn.fetchrow(
                """
                INSERT INTO users (username, email, password_hash, role)
                VALUES ($1, $2, $3, $4)
                RETURNING user_id, username, email, role, created_at, is_active
                """,
                user.username, user.email, hashed_password, user.role
            )

            # Create user profile
            await conn.execute(
                """
                INSERT INTO user_profiles (user_id)
                VALUES ($1)
                """,
                new_user['user_id']
            )

            return dict(new_user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.post("/admin/register", response_model=UserOut)
async def register_admin(
    user: UserCreate,
    current_user: UserOut = Depends(get_current_user)
):
    """Register a new admin user (admin only)"""
    # Check if current user is admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create admin accounts"
        )
    
    # Ensure the new user is an admin
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This endpoint can only create admin accounts"
        )
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if username or email already exists
            existing_user = await conn.fetchrow(
                "SELECT username, email FROM users WHERE username = $1 OR email = $2",
                user.username, user.email
            )
            if existing_user:
                if existing_user['username'] == user.username:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Username already registered"
                    )
                if existing_user['email'] == user.email:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email already registered"
                    )

            # Hash the password
            hashed_password = pwd_context.hash(user.password)

            # Create admin user
            new_user = await conn.fetchrow(
                """
                INSERT INTO users (username, email, password_hash, role)
                VALUES ($1, $2, $3, $4)
                RETURNING user_id, username, email, role, created_at, is_active
                """,
                user.username, user.email, hashed_password, "admin"
            )

            # Create user profile
            await conn.execute(
                """
                INSERT INTO user_profiles (user_id)
                VALUES ($1)
                """,
                new_user['user_id']
            )

            return dict(new_user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.post("/login", response_model=Token)
async def login(
    user_credentials: UserLogin,
    response: Response,
    rate_limiter: RateLimiter = Depends(RateLimiter(limit=MAX_LOGIN_ATTEMPTS, window=LOGIN_TIMEOUT_MINUTES * 60))
):
    # Check rate limiting - Now handled by RateLimiter dependency
    # if not check_rate_limit(user_credentials.email):
    #     raise HTTPException(
    #         status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    #         detail=f"Too many login attempts. Please try again in {LOGIN_TIMEOUT_MINUTES} minutes"
    #     )
    
    conn = await get_pg_connection()
    try:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE email = $1",
            user_credentials.email
        )
        
        # Use constant time comparison for password verification
        if not user or not verify_password(user_credentials.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": user["email"]}, expires_delta=access_token_expires
        )
        
        # Set security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return {"access_token": access_token, "token_type": "bearer"}
    finally:
        await conn.close()

@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    # Add token to blacklist
    TOKEN_BLACKLIST[token] = time.time()
    return {"message": "Successfully logged out"}

@router.get("/me", response_model=UserOut)
async def read_users_me(current_user = Depends(get_current_user)):
    try:
        # Convert asyncpg Record to dict
        user_dict = dict(current_user)
        
        # Create UserOut model from dict
        user_out = UserOut(**user_dict)
        return user_out
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing user data"
        )

@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """Request password reset"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if user exists
            user = await conn.fetchrow(
                "SELECT user_id, username, email FROM users WHERE email = $1",
                request.email
            )
            
            if not user:
                # Return success even if user doesn't exist for security
                return {"message": "If your email is registered, you will receive a password reset link"}
            
            # Create reset token
            reset_token = create_access_token(
                data={"sub": user["email"], "type": "reset"},
                expires_delta=timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
            )
            
            # Send reset email
            frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
            email_sent = await send_reset_password_email(
                email=user["email"],
                username=user["username"],
                reset_token=reset_token,
                frontend_url=frontend_url
            )
            
            if not email_sent:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to send reset email"
                )
            
            return {"message": "If your email is registered, you will receive a password reset link"}
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """Reset password using token"""
    try:
        # Verify token
        payload = jwt.decode(request.token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        token_type = payload.get("type")
        
        if not email or token_type != "reset":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid reset token"
            )
        
        # Hash new password
        hashed_password = pwd_context.hash(request.new_password)
        
        pool = await get_pg_connection()
        try:
            async with pool.acquire() as conn:
                # Update password
                result = await conn.execute(
                    "UPDATE users SET password_hash = $1 WHERE email = $2",
                    hashed_password, email
                )
                
                if result == "UPDATE 0":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid reset token"
                    )
                
                return {"message": "Password has been reset successfully"}
                
        finally:
            await pool.close()
            
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

def require_role(roles: List[str]):
    """Dependency to check if user has required role"""
    async def role_checker(current_user: UserOut = Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not authorized. Required roles: {', '.join(roles)}"
            )
        return current_user
    return role_checker


