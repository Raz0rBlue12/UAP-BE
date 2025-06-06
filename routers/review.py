from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from models.review import ReviewCreate, ReviewOut, ReviewUpdate
from models.user import UserOut
from db.client import get_pg_connection
from routers.auth import get_current_user
from datetime import datetime

router = APIRouter(
    prefix="/reviews",
    tags=["reviews"]
)

@router.post("", response_model=ReviewOut)
async def create_review(
    review: ReviewCreate,
    current_user: UserOut = Depends(get_current_user)
):
    """Create a new review"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if product exists
            product = await conn.fetchrow(
                "SELECT * FROM products WHERE product_id = $1",
                review.product_id
            )
            if not product:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            # Check if user has already reviewed this product
            existing_review = await conn.fetchrow(
                "SELECT * FROM reviews WHERE user_id = $1 AND product_id = $2",
                current_user.user_id,
                review.product_id
            )
            if existing_review:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User has already reviewed this product"
                )
            
            # Create review
            query = """
                INSERT INTO reviews (product_id, user_id, rating, comment)
                VALUES ($1, $2, $3, $4)
                RETURNING review_id, product_id, user_id, rating, comment, created_at
            """
            result = await conn.fetchrow(
                query,
                review.product_id,
                current_user.user_id,
                review.rating,
                review.comment
            )
            
            # Update product rating
            await conn.execute("""
                UPDATE products 
                SET rating = (
                    SELECT AVG(rating) 
                    FROM reviews 
                    WHERE product_id = $1
                )
                WHERE product_id = $1
            """, review.product_id)
            
            return dict(result)
    finally:
        await pool.close()

@router.get("/product/{product_id}", response_model=List[ReviewOut])
async def get_product_reviews(product_id: int):
    """Get all reviews for a product"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            query = """
                SELECT r.*, u.username, u.email, u.role
                FROM reviews r
                JOIN users u ON r.user_id = u.user_id
                WHERE r.product_id = $1
                ORDER BY r.created_at DESC
            """
            rows = await conn.fetch(query, product_id)
            return [dict(row) for row in rows]
    finally:
        await pool.close()

@router.get("/me", response_model=List[ReviewOut])
async def get_user_reviews(current_user: UserOut = Depends(get_current_user)):
    """Get all reviews by the current user"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            query = """
                SELECT r.*, p.name as product_name, p.description, p.price, p.category
                FROM reviews r
                JOIN products p ON r.product_id = p.product_id
                WHERE r.user_id = $1
                ORDER BY r.created_at DESC
            """
            rows = await conn.fetch(query, current_user.user_id)
            return [dict(row) for row in rows]
    finally:
        await pool.close()

@router.put("/{review_id}", response_model=ReviewOut)
async def update_review(
    review_id: int,
    review_update: ReviewUpdate,
    current_user: UserOut = Depends(get_current_user)
):
    """Update a review"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if review exists and belongs to user
            review = await conn.fetchrow(
                "SELECT * FROM reviews WHERE review_id = $1 AND user_id = $2",
                review_id,
                current_user.user_id
            )
            if not review:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Review not found"
                )
            
            # Update review
            query = """
                UPDATE reviews 
                SET rating = $1, comment = $2
                WHERE review_id = $3
                RETURNING review_id, product_id, user_id, rating, comment, created_at
            """
            result = await conn.fetchrow(
                query,
                review_update.rating,
                review_update.comment,
                review_id
            )
            
            # Update product rating
            await conn.execute("""
                UPDATE products 
                SET rating = (
                    SELECT AVG(rating) 
                    FROM reviews 
                    WHERE product_id = $1
                )
                WHERE product_id = $1
            """, review["product_id"])
            
            return dict(result)
    finally:
        await pool.close()

@router.delete("/{review_id}")
async def delete_review(
    review_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Delete a review"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if review exists and belongs to user
            review = await conn.fetchrow(
                "SELECT * FROM reviews WHERE review_id = $1 AND user_id = $2",
                review_id,
                current_user.user_id
            )
            if not review:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Review not found"
                )
            
            # Delete review
            await conn.execute(
                "DELETE FROM reviews WHERE review_id = $1",
                review_id
            )
            
            # Update product rating
            await conn.execute("""
                UPDATE products 
                SET rating = (
                    SELECT COALESCE(AVG(rating), 0)
                    FROM reviews 
                    WHERE product_id = $1
                )
                WHERE product_id = $1
            """, review["product_id"])
            
            return {"message": "Review successfully deleted"}
    finally:
        await pool.close() 