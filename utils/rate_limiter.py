from fastapi import Request, HTTPException, status
from collections import defaultdict
import time

# In-memory storage for rate limiting
# Consider using Redis or another persistent store in production
rate_limit_storage = defaultdict(list)

class RateLimiter:
    """FastAPI dependency for IP-based rate limiting"""
    def __init__(self, limit: int = 100, window: int = 60): # limit requests per window seconds
        self.limit = limit
        self.window = window

    async def __call__(self, request: Request):
        client_ip = request.client.host
        current_time = time.time()

        # Clean up old timestamps outside the window
        rate_limit_storage[client_ip] = [
            t for t in rate_limit_storage[client_ip] if current_time - t < self.window
        ]

        # Check if limit is exceeded
        if len(rate_limit_storage[client_ip]) >= self.limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests from {client_ip}. Please try again later."
            )

        # Add current timestamp
        rate_limit_storage[client_ip].append(current_time) 