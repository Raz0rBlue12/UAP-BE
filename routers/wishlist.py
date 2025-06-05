from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from db.client import get_pg_connection
from models.wishlist import WishlistItemCreate, WishlistItemOut
from routers.auth import get_current_user

router = APIRouter(
    prefix="/wishlist",
    tags=["Wishlist"]
)

@router.post("/", response_model=WishlistItemOut, status_code=status.HTTP_201_CREATED)
async def add_to_wishlist(
    item: WishlistItemCreate,
    current_user = Depends(get_current_user)
):
    """Add a product to the user's wishlist"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if the product exists (optional but recommended)
            product = await conn.fetchrow("SELECT product_id FROM products WHERE product_id = $1", item.product_id)
            if not product:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

            # Check if the item is already in the wishlist
            existing_item = await conn.fetchrow(
                "SELECT wishlist_id FROM wishlists WHERE user_id = $1 AND product_id = $2",
                current_user['user_id'], item.product_id
            )
            if existing_item:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product already in wishlist")

            # Add item to wishlist
            new_item = await conn.fetchrow(
                "INSERT INTO wishlists (user_id, product_id) VALUES ($1, $2) RETURNING wishlist_id, user_id, product_id",
                current_user['user_id'], item.product_id
            )
            return WishlistItemOut(**dict(new_item))
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

@router.get("/", response_model=List[WishlistItemOut])
async def get_wishlist(
    current_user = Depends(get_current_user)
):
    """Get the user's wishlist"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            items = await conn.fetch(
                "SELECT wishlist_id, user_id, product_id FROM wishlists WHERE user_id = $1",
                current_user['user_id']
            )
            return [WishlistItemOut(**dict(item)) for item in items]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_wishlist(
    product_id: int,
    current_user = Depends(get_current_user)
):
    """Remove a product from the user's wishlist"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if the item exists in the wishlist and belongs to the user
            result = await conn.execute(
                "DELETE FROM wishlists WHERE user_id = $1 AND product_id = $2",
                current_user['user_id'], product_id
            )
            if result != "DELETE 1":
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found in wishlist")
            return # No content on successful deletion
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close() 