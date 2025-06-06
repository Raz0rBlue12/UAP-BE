from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from routers import auth, user, product, cart, wishlist, notification, review, purchase, payment, message
from db.client import get_pg_connection

app = FastAPI(
    title="UAP E-Commerce API",
    description="API for UAP E-Commerce Platform",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(user.router)
app.include_router(product.router)
app.include_router(cart.router)
app.include_router(wishlist.router)
app.include_router(notification.router)
app.include_router(review.router)
app.include_router(purchase.router)
app.include_router(payment.router)
app.include_router(message.router)

@app.get("/")
async def root():
    return {"message": "Welcome to E-Commerce API"}

@app.get("/test-db")
async def test_db_connection():
    try:
        conn = await get_pg_connection()
        # Test the connection by executing a simple query
        await conn.execute("SELECT 1")
        await conn.close()
        return {"status": "success", "message": "Database connection successful"}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Database connection failed: {str(e)}"
        )
