import asyncio
import os
import sys
from pathlib import Path

# Add project root to Python path
project_root = str(Path(__file__).parent.parent)
sys.path.append(project_root)

from dotenv import load_dotenv
from passlib.context import CryptContext
from db.client import get_pg_connection

load_dotenv()

# Password hashing configuration
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12
)

def validate_password(password: str) -> bool:
    """Validate password strength"""
    if len(password) < 8:
        return False
    
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)
    
    return has_upper and has_lower and has_digit and has_special

async def create_admin_user():
    """Create admin user with interactive input"""
    print("\n=== Create Admin User ===\n")
    
    # Get admin credentials
    while True:
        admin_username = input("Enter admin username: ").strip()
        if admin_username:
            break
        print("Username cannot be empty")
    
    while True:
        admin_email = input("Enter admin email: ").strip()
        if admin_email and '@' in admin_email:
            break
        print("Please enter a valid email address")
    
    while True:
        admin_password = input("Enter admin password: ").strip()
        if validate_password(admin_password):
            break
        print("Password must be at least 8 characters long and contain uppercase, lowercase, numbers, and special characters")
    
    # Confirm password
    confirm_password = input("Confirm admin password: ").strip()
    if admin_password != confirm_password:
        print("Passwords do not match")
        return
    
    # Hash password
    hashed_password = pwd_context.hash(admin_password)
    
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check if admin already exists
                existing_admin = await conn.fetchrow(
                    "SELECT * FROM users WHERE role = 'admin'"
                )
                
                if existing_admin:
                    print("\nError: An admin user already exists")
                    return
                
                # Check if username or email is taken
                existing_user = await conn.fetchrow(
                    "SELECT * FROM users WHERE username = $1 OR email = $2",
                    admin_username, admin_email
                )
                
                if existing_user:
                    print("\nError: Username or email already taken")
                    return
                
                # Create admin user
                admin = await conn.fetchrow(
                    """
                    INSERT INTO users (username, email, password_hash, role)
                    VALUES ($1, $2, $3, 'admin')
                    RETURNING user_id, username, email, role
                    """,
                    admin_username, admin_email, hashed_password
                )
                
                # Create admin profile
                await conn.execute(
                    """
                    INSERT INTO user_profiles (user_id, full_name, bio)
                    VALUES ($1, $2, $3)
                    """,
                    admin['user_id'],
                    f"Admin {admin_username}",
                    "System Administrator"
                )
                
                print("\n=== Admin User Created Successfully! ===")
                print(f"Username: {admin['username']}")
                print(f"Email: {admin['email']}")
                print(f"Role: {admin['role']}")
                print("\nPlease keep these credentials secure!")
                print("You can now login using these credentials at /auth/login")
                
    except Exception as e:
        print(f"\nError creating admin user: {str(e)}")
    finally:
        await pool.close()

if __name__ == "__main__":
    print("Starting admin user creation...")
    asyncio.run(create_admin_user())
