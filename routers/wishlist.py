from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from models.wishlist import WishlistOut, WishlistCreate
from models.product import ProductOut
from models.user import UserOut
from db.client import get_pg_connection
from routers.auth import get_current_user
from datetime import datetime
from pydantic import BaseModel

class MessageResponse(BaseModel):
    message: str

router = APIRouter(
    prefix="/wishlist",
    tags=["wishlist"]
)

@router.get("", response_model=List[WishlistOut])
async def get_wishlist(current_user: UserOut = Depends(get_current_user)):
    """Get user's wishlist"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Get wishlist items with product details
            query = """
                SELECT w.wishlist_id, w.user_id, w.product_id, w.created_at,
                       p.name, p.description, p.price, p.stock, p.category,
                       p.rating, p.status, p.created_at as product_created_at,
                       p.updated_at as product_updated_at, p.seller_id
                FROM wishlists w
                JOIN products p ON w.product_id = p.product_id
                WHERE w.user_id = $1
                ORDER BY w.created_at DESC
            """
            rows = await conn.fetch(query, current_user.user_id)
            
            # Format response
            wishlist = []
            for row in rows:
                # Get product images
                images_query = """
                    SELECT image_id, image_url, uploaded_at
                    FROM product_images
                    WHERE product_id = $1
                    ORDER BY uploaded_at ASC
                """
                images = await conn.fetch(images_query, row['product_id'])
                
                wishlist.append({
                    "wishlist_id": row['wishlist_id'],
                    "user_id": row['user_id'],
                    "product_id": row['product_id'],
                    "created_at": row['created_at'],
                    "product": {
                        "product_id": row['product_id'],
                        "seller_id": row['seller_id'],
                        "name": row['name'],
                        "description": row['description'],
                        "price": float(row['price']),
                        "stock": row['stock'],
                        "category": row['category'],
                        "rating": float(row['rating']) if row['rating'] else 0.0,
                        "status": row['status'],
                        "created_at": row['product_created_at'],
                        "updated_at": row['product_updated_at'],
                        "images": [
                            {
                                "image_id": img['image_id'],
                                "image_url": img['image_url'],
                                "uploaded_at": img['uploaded_at']
                            } for img in images
                        ]
                    }
                })
            
            return wishlist
    finally:
        await pool.close()

@router.post("", response_model=WishlistOut, status_code=status.HTTP_201_CREATED)
async def add_to_wishlist(
    wishlist_item: WishlistCreate,
    current_user: UserOut = Depends(get_current_user)
):
    """Add product to wishlist"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if product exists
            product_query = "SELECT * FROM products WHERE product_id = $1"
            product = await conn.fetchrow(product_query, wishlist_item.product_id)
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            # Check if already in wishlist
            check_query = """
                SELECT * FROM wishlists 
                WHERE user_id = $1 AND product_id = $2
            """
            existing = await conn.fetchrow(check_query, current_user.user_id, wishlist_item.product_id)
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Product already in wishlist"
                )
            
            # Add to wishlist
            insert_query = """
                INSERT INTO wishlists (user_id, product_id, created_at)
                VALUES ($1, $2, $3)
                RETURNING wishlist_id, user_id, product_id, created_at
            """
            wishlist_item = await conn.fetchrow(
                insert_query,
                current_user.user_id,
                wishlist_item.product_id,
                datetime.utcnow()
            )
            
            # Get product images
            images_query = """
                SELECT image_id, image_url, uploaded_at
                FROM product_images
                WHERE product_id = $1
                ORDER BY uploaded_at ASC
            """
            images = await conn.fetch(images_query, product['product_id'])
            
            return {
                "wishlist_id": wishlist_item['wishlist_id'],
                "user_id": wishlist_item['user_id'],
                "product_id": wishlist_item['product_id'],
                "created_at": wishlist_item['created_at'],
                "product": {
                    "product_id": product['product_id'],
                    "seller_id": product['seller_id'],
                    "name": product['name'],
                    "description": product['description'],
                    "price": float(product['price']),
                    "stock": product['stock'],
                    "category": product['category'],
                    "rating": float(product['rating']) if product['rating'] else 0.0,
                    "status": product['status'],
                    "created_at": product['created_at'],
                    "updated_at": product['updated_at'],
                    "images": [
                        {
                            "image_id": img['image_id'],
                            "image_url": img['image_url'],
                            "uploaded_at": img['uploaded_at']
                        } for img in images
                    ]
                }
            }
    finally:
        await pool.close()

@router.delete("/{product_id}", response_model=MessageResponse)
async def remove_from_wishlist(
    product_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Remove product from wishlist"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if product exists in wishlist
            check_query = """
                SELECT * FROM wishlists 
                WHERE user_id = $1 AND product_id = $2
            """
            existing = await conn.fetchrow(check_query, current_user.user_id, product_id)
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not in wishlist"
                )
            
            # Remove from wishlist
            delete_query = """
                DELETE FROM wishlists 
                WHERE user_id = $1 AND product_id = $2
            """
            await conn.execute(delete_query, current_user.user_id, product_id)
            
            return {"message": "Product successfully removed from wishlist"}
    finally:
        await pool.close()

@router.get("/check/{product_id}")
async def check_wishlist_status(
    product_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Check if product is in user's wishlist"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if product exists
            product_query = "SELECT * FROM products WHERE product_id = $1"
            product = await conn.fetchrow(product_query, product_id)
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            # Check if in wishlist
            check_query = """
                SELECT * FROM wishlists 
                WHERE user_id = $1 AND product_id = $2
            """
            existing = await conn.fetchrow(check_query, current_user.user_id, product_id)
            
            return {"is_in_wishlist": bool(existing)}
    finally:
        await pool.close() 