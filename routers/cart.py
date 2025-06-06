from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from db.client import get_pg_connection
from models.cart import CartItemCreate, CartItemOut, CartItemUpdate, ProductImage
from routers.auth import get_current_user
from models.user import UserOut
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(
    prefix="/cart",
    tags=["Cart"]
)

class DeleteResponse(BaseModel):
    message: str

@router.post("/", response_model=CartItemOut, status_code=status.HTTP_201_CREATED)
async def add_to_cart(
    item: CartItemCreate,
    current_user: UserOut = Depends(get_current_user)
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
                current_user.user_id, item.product_id
            )

            if existing_item:
                # Update quantity
                new_quantity = existing_item['quantity'] + item.quantity
                
                # Check if new quantity exceeds stock
                if new_quantity > product['stock']:
                     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough stock available")

                updated_item = await conn.fetchrow(
                    """
                    UPDATE shopping_cart sc
                    SET quantity = $1
                    FROM products p
                    WHERE sc.cart_id = $2 AND sc.product_id = p.product_id
                    RETURNING 
                        sc.cart_id, sc.user_id, sc.product_id, sc.quantity,
                        p.name as product_name, p.description as product_description,
                        p.price as product_price, p.stock as product_stock,
                        p.category as product_category, p.rating as product_rating
                    """,
                    new_quantity, existing_item['cart_id']
                )
                
                # Get product images
                images = await conn.fetch(
                    "SELECT image_id, image_url, uploaded_at FROM product_images WHERE product_id = $1",
                    updated_item['product_id']
                )
                
                item_dict = dict(updated_item)
                item_dict['product_images'] = [dict(img) for img in images]
                return CartItemOut(**item_dict)
            else:
                # Add new item to cart
                # Check if initial quantity exceeds stock
                if item.quantity > product['stock']:
                     raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not enough stock available")
                     
                new_item = await conn.fetchrow(
                    """
                    INSERT INTO shopping_cart (user_id, product_id, quantity)
                    SELECT $1, $2, $3
                    FROM products p
                    WHERE p.product_id = $2
                    RETURNING 
                        cart_id, user_id, product_id, quantity,
                        (SELECT name FROM products WHERE product_id = $2) as product_name,
                        (SELECT description FROM products WHERE product_id = $2) as product_description,
                        (SELECT price FROM products WHERE product_id = $2) as product_price,
                        (SELECT stock FROM products WHERE product_id = $2) as product_stock,
                        (SELECT category FROM products WHERE product_id = $2) as product_category,
                        (SELECT rating FROM products WHERE product_id = $2) as product_rating
                    """,
                    current_user.user_id, item.product_id, item.quantity
                )
                
                # Get product images
                images = await conn.fetch(
                    "SELECT image_id, image_url, uploaded_at FROM product_images WHERE product_id = $1",
                    new_item['product_id']
                )
                
                item_dict = dict(new_item)
                item_dict['product_images'] = [dict(img) for img in images]
                return CartItemOut(**item_dict)
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

@router.get("/", response_model=List[CartItemOut])
async def get_cart(
    current_user: UserOut = Depends(get_current_user)
):
    """Get the user's shopping cart with product details"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            items = await conn.fetch(
                """
                SELECT 
                    sc.cart_id,
                    sc.user_id,
                    sc.product_id,
                    sc.quantity,
                    p.name as product_name,
                    p.description as product_description,
                    p.price as product_price,
                    p.stock as product_stock,
                    p.category as product_category,
                    p.rating as product_rating
                FROM shopping_cart sc
                JOIN products p ON sc.product_id = p.product_id
                WHERE sc.user_id = $1
                """,
                current_user.user_id
            )
            
            # Get images for each product
            result = []
            for item in items:
                item_dict = dict(item)
                images = await conn.fetch(
                    "SELECT image_id, image_url, uploaded_at FROM product_images WHERE product_id = $1",
                    item['product_id']
                )
                item_dict['product_images'] = [dict(img) for img in images]
                result.append(CartItemOut(**item_dict))
            
            return result
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

@router.put("/{cart_item_id}", response_model=CartItemOut)
async def update_cart_item(
    cart_item_id: int,
    item_update: CartItemUpdate,
    current_user: UserOut = Depends(get_current_user)
):
    """Update the quantity of a cart item"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if the item exists in the cart and belongs to the user
            existing_item = await conn.fetchrow(
                "SELECT cart_id, user_id, product_id FROM shopping_cart WHERE cart_id = $1 AND user_id = $2",
                cart_item_id, current_user.user_id
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
                """
                UPDATE shopping_cart sc
                SET quantity = $1
                FROM products p
                WHERE sc.cart_id = $2 AND sc.product_id = p.product_id
                RETURNING 
                    sc.cart_id, sc.user_id, sc.product_id, sc.quantity,
                    p.name as product_name, p.description as product_description,
                    p.price as product_price, p.stock as product_stock,
                    p.category as product_category, p.rating as product_rating
                """,
                item_update.quantity, cart_item_id
            )
            
            # Get product images
            images = await conn.fetch(
                "SELECT image_id, image_url, uploaded_at FROM product_images WHERE product_id = $1",
                updated_item['product_id']
            )
            
            item_dict = dict(updated_item)
            item_dict['product_images'] = [dict(img) for img in images]
            return CartItemOut(**item_dict)
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

@router.delete("/{cart_item_id}", response_model=DeleteResponse)
async def remove_from_cart(
    cart_item_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Remove an item from the user's shopping cart"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if the item exists in the cart and belongs to the user
            result = await conn.execute(
                "DELETE FROM shopping_cart WHERE cart_id = $1 AND user_id = $2",
                cart_item_id, current_user.user_id
            )
            if result != "DELETE 1":
                 raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found or does not belong to user")
            return DeleteResponse(message="Item successfully removed from cart")
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close() 