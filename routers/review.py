from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from db.client import get_pg_connection
from models.review import ReviewCreate, ReviewOut
from routers.auth import get_current_user
from routers.auth import require_role

router = APIRouter(
    prefix="/reviews",
    tags=["Reviews"]
)

async def update_product_rating(conn, product_id: int):
    """Calculate and update the average rating for a product"""
    reviews = await conn.fetch(
        "SELECT rating FROM reviews WHERE product_id = $1",
        product_id
    )
    if not reviews:
        average_rating = 0.0
    else:
        total_rating = sum(r['rating'] for r in reviews)
        average_rating = total_rating / len(reviews)

    await conn.execute(
        "UPDATE products SET rating = $1 WHERE product_id = $2",
        average_rating, product_id
    )

@router.post("/", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
async def create_review(
    review: ReviewCreate,
    current_user = Depends(get_current_user) # Only logged-in users can review
):
    """Submit a new review for a product"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check if product exists
                product = await conn.fetchrow("SELECT product_id FROM products WHERE product_id = $1", review.product_id)
                if not product:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

                # Check if user has already reviewed this product (optional, depending on business logic)
                existing_review = await conn.fetchrow(
                    "SELECT review_id FROM reviews WHERE user_id = $1 AND product_id = $2",
                    current_user['user_id'], review.product_id
                )
                if existing_review:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You have already reviewed this product")

                # Insert the new review
                new_review = await conn.fetchrow(
                    "INSERT INTO reviews (product_id, user_id, rating, comment) VALUES ($1, $2, $3, $4) RETURNING review_id, product_id, user_id, rating, comment, created_at",
                    review.product_id,
                    current_user['user_id'],
                    review.rating,
                    review.comment
                )

                # Update product average rating
                await update_product_rating(conn, review.product_id)

                return ReviewOut(**dict(new_review))
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

@router.get("/{product_id}", response_model=List[ReviewOut])
async def get_reviews_for_product(
    product_id: int
):
    """Get all reviews for a specific product"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
             # Check if product exists (optional but recommended)
            product = await conn.fetchrow("SELECT product_id FROM products WHERE product_id = $1", product_id)
            if not product:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
                
            reviews = await conn.fetch(
                "SELECT review_id, product_id, user_id, rating, comment, created_at FROM reviews WHERE product_id = $1 ORDER BY created_at DESC",
                product_id
            )
            return [ReviewOut(**dict(r)) for r in reviews]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

# Optional: Add endpoints for updating and deleting reviews
# @router.put("/{review_id}", response_model=ReviewOut)
# async def update_review(...

# @router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
# async def delete_review(... 