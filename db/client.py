from supabase import create_client, Client
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def get_pg_connection():
    """Get PostgreSQL connection"""
    return await asyncpg.create_pool(
        dsn=os.getenv("DATABASE_URL"),
        min_size=1,
        max_size=10,
        statement_cache_size=0  # Disable statement cache to avoid conflicts
    )
