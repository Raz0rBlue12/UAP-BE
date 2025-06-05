from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from db.client import get_pg_connection
from models.cart import CartItemCreate, CartItemOut, CartItemUpdate
from routers.auth import get_current_user

router = APIRouter(
    prefix="/cart",
    tags=["Cart"]
)

@router.post("/", response_model=CartItemOut, status_code=status.HTTP_201_CREATED)
async def add_to_cart(
    item: CartItemCreate,
    current_user = Depends(get_current_user)
):
    """Add a product to the user's shopping cart or update quantity if already exists"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if the product exists and get its stock
            product = await conn.fetchrow("SELECT product_id, stock FROM products WHERE product_id = $1", item.product_id)
            if not product:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

            # Check if the item is already in the cart
            existing_item = await conn.fetchrow(
                "SELECT cart_id, quantity FROM shopping_cart WHERE user_id = $1 AND product_id = $2",
                current_user['user_id'], item.product_id
            )

            if existing_item:
                # Update quantity
                new_quantity = existing_item['quantity'] + item.quantity
                
                # Check if new quantity exceeds stock
                if new_quantity > product['stock']:
                     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough stock available")

                updated_item = await conn.fetchrow(
                    "UPDATE shopping_cart SET quantity = $1 WHERE cart_id = $2 RETURNING cart_id, user_id, product_id, quantity",
                    new_quantity, existing_item['cart_id']
                )
                return CartItemOut(**dict(updated_item))
            else:
                # Add new item to cart
                # Check if initial quantity exceeds stock
                if item.quantity > product['stock']:
                     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough stock available")
                     
                new_item = await conn.fetchrow(
                    "INSERT INTO shopping_cart (user_id, product_id, quantity) VALUES ($1, $2, $3) RETURNING cart_id, user_id, product_id, quantity",
                    current_user['user_id'], item.product_id, item.quantity
                )
                return CartItemOut(**dict(new_item))
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

@router.get("/", response_model=List[CartItemOut])
async def get_cart(
    current_user = Depends(get_current_user)
):
    """Get the user's shopping cart"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            items = await conn.fetch(
                "SELECT cart_id, user_id, product_id, quantity FROM shopping_cart WHERE user_id = $1",
                current_user['user_id']
            )
            return [CartItemOut(**dict(item)) for item in items]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

@router.put("/{cart_item_id}", response_model=CartItemOut)
async def update_cart_item(
    cart_item_id: int,
    item_update: CartItemUpdate,
    current_user = Depends(get_current_user)
):
    """Update the quantity of a cart item"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if the item exists in the cart and belongs to the user
            existing_item = await conn.fetchrow(
                "SELECT cart_id, user_id, product_id FROM shopping_cart WHERE cart_id = $1 AND user_id = $2",
                cart_item_id, current_user['user_id']
            )
            if not existing_item:
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found or does not belong to user")

            # Get product stock
            product = await conn.fetchrow("SELECT stock FROM products WHERE product_id = $1", existing_item['product_id'])
            if not product:
                 # This case should ideally not happen if product_id has a foreign key constraint
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Associated product not found")

            # Check if new quantity exceeds stock
            if item_update.quantity > product['stock']:
                 raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough stock available")

            # Update quantity
            updated_item = await conn.fetchrow(
                "UPDATE shopping_cart SET quantity = $1 WHERE cart_id = $2 RETURNING cart_id, user_id, product_id, quantity",
                item_update.quantity, cart_item_id
            )
            return CartItemOut(**dict(updated_item))
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

@router.delete("/{cart_item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_cart(
    cart_item_id: int,
    current_user = Depends(get_current_user)
):
    """Remove an item from the user's shopping cart"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if the item exists in the cart and belongs to the user
            result = await conn.execute(
                "DELETE FROM shopping_cart WHERE cart_id = $1 AND user_id = $2",
                cart_item_id, current_user['user_id']
            )
            if result != "DELETE 1":
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found or does not belong to user")
            return # No content on successful deletion
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close() 