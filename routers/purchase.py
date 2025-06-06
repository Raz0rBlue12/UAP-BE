from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from db.client import get_pg_connection
from models.purchase import OrderCreate, OrderOut, OrderUpdate, OrderItemOut, ShippingAddress
from models.user import UserOut
from routers.auth import get_current_user, require_role
from utils.rate_limiter import RateLimiter
import logging
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/purchases",
    tags=["Purchases"]
)

@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(
    order_data: OrderCreate,
    current_user: UserOut = Depends(get_current_user)
):
    """Create a new order with multiple items"""
    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            total_amount = Decimal(0)
            order_items_to_insert = []
            product_updates = []
            requires_shipping = False

            # Process each item, calculate total amount, check stock, and prepare inserts/updates
            for item in order_data.items:
                # Fetch product price, stock, and type
                product = await conn.fetchrow(
                    "SELECT product_id, price, stock, product_type FROM products WHERE product_id = $1",
                    item.product_id
                )
                if not product:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Product {item.product_id} not found"
                    )

                if product["stock"] < item.quantity:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Not enough stock for product {item.product_id}"
                    )

                # Check if any product requires shipping
                if product["product_type"] == "physical":
                    requires_shipping = True

                # Calculate price for this item and add to total amount
                item_total_price = product["price"] * item.quantity
                total_amount += item_total_price

                # Prepare data for order_items insert
                order_items_to_insert.append({
                    "product_id": item.product_id,
                    "quantity": item.quantity,
                    "total_price": item_total_price
                })

                # Prepare data for product stock update
                product_updates.append({
                    "product_id": item.product_id,
                    "quantity_to_decrease": item.quantity
                })

            # Validate shipping address requirement
            if requires_shipping and not order_data.shipping_address:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Shipping address is required for orders containing physical products"
                )

            # Convert shipping address to JSON string if provided
            shipping_address_json = None
            if order_data.shipping_address:
                shipping_address_json = order_data.shipping_address.model_dump_json()

            # Insert the main order record
            insert_order_query = """
                INSERT INTO orders (
                    user_id, shipping_address, payment_method, total_amount, status
                )
                VALUES ($1, $2, $3, $4, 'pending')
                RETURNING order_id, user_id, shipping_address, payment_method, total_amount,
                          status, created_at, updated_at
            """
            new_order = await conn.fetchrow(
                insert_order_query,
                current_user.user_id,
                shipping_address_json,
                order_data.payment_method,
                total_amount
            )
            order_id = new_order['order_id']

            # Insert order items
            insert_item_query = """
                INSERT INTO order_items (
                    order_id, product_id, quantity, total_price
                )
                VALUES ($1, $2, $3, $4)
            """
            for item_data in order_items_to_insert:
                await conn.execute(
                    insert_item_query,
                    order_id,
                    item_data["product_id"],
                    item_data["quantity"],
                    item_data["total_price"]
                )

            # Update product stock (perform updates after successful order/item inserts)
            update_stock_query = "UPDATE products SET stock = stock - $1 WHERE product_id = $2"
            for update_data in product_updates:
                 await conn.execute(
                    update_stock_query,
                    update_data["quantity_to_decrease"],
                    update_data["product_id"]
                 )

            # Fetch the complete order with items for the response
            # This requires joining orders, order_items, and products tables
            fetch_order_query = """
                SELECT
                    o.order_id,
                    o.user_id,
                    o.shipping_address,
                    o.payment_method,
                    o.total_amount,
                    o.status,
                    o.created_at,
                    o.updated_at,
                    o.tracking_number,
                    o.estimated_delivery,
                    oi.purchase_id as order_item_id,
                    oi.product_id,
                    oi.quantity,
                    oi.total_price as item_total_price, -- Alias to avoid conflict with order_total_amount
                    p.name as product_name,
                    pi.image_url as product_image
                FROM orders o
                JOIN order_items oi ON o.order_id = oi.order_id
                JOIN products p ON oi.product_id = p.product_id
                LEFT JOIN product_images pi ON p.product_id = pi.product_id -- Join to get product image
                WHERE o.order_id = $1
            """
            order_records = await conn.fetch(fetch_order_query, order_id)

            if not order_records:
                # Should not happen if insert was successful, but as a safeguard
                 raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch created order")

            # Structure the response into OrderOut model
            # The first record contains the main order details
            main_order_data = dict(order_records[0])
            order_out_items = []

            # Parse shipping address from JSON if it exists
            shipping_address = None
            if main_order_data['shipping_address']:
                try:
                    shipping_address = ShippingAddress.model_validate_json(main_order_data['shipping_address'])
                except Exception as e:
                    logger.error(f"Error parsing shipping address: {e}")
                    # Continue without shipping address if parsing fails

            for record in order_records:
                 order_out_items.append(OrderItemOut(
                     order_item_id=record['order_item_id'],
                     order_id=record['order_id'],
                     product_id=record['product_id'],
                     quantity=record['quantity'],
                     total_price=record['item_total_price'], # Use the item total price alias
                     product_name=record['product_name'],
                     product_image=record['product_image']
                 ))

            # Create the final OrderOut object
            order_out = OrderOut(
                order_id=main_order_data['order_id'],
                user_id=main_order_data['user_id'],
                shipping_address=shipping_address,
                payment_method=main_order_data['payment_method'],
                total_amount=main_order_data['total_amount'],
                status=main_order_data['status'],
                created_at=main_order_data['created_at'],
                updated_at=main_order_data['updated_at'],
                tracking_number=main_order_data['tracking_number'],
                estimated_delivery=main_order_data['estimated_delivery'],
                items=order_out_items
            )

            return order_out

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        # Rollback transaction if any error occurs before explicit commit
        # The async with conn.transaction() handles rollback on exception
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        if conn:
            await pool.release(conn)

# Helper function to fetch order details including items
async def fetch_order_details(conn, order_id: int, user_id: Optional[int] = None):
    query = """
        SELECT
            o.order_id,
            o.user_id,
            o.shipping_address,
            o.payment_method,
            o.total_amount,
            o.status,
            o.created_at,
            o.updated_at,
            o.tracking_number,
            o.estimated_delivery,
            oi.purchase_id as order_item_id,
            oi.product_id,
            oi.quantity,
            oi.total_price as item_total_price,
            p.name as product_name,
            pi.image_url as product_image
        FROM orders o
        JOIN order_items oi ON o.order_id = oi.order_id
        JOIN products p ON oi.product_id = p.product_id
        LEFT JOIN product_images pi ON p.product_id = pi.product_id
        WHERE o.order_id = $1
    """
    params = [order_id]

    if user_id is not None:
        query += " AND o.user_id = $2"
        params.append(user_id)

    order_records = await conn.fetch(query, *params)

    if not order_records:
        return None

    # Structure the data into OrderOut model
    main_order_data = dict(order_records[0])
    order_out_items = []

    # Parse shipping address from JSON if it exists
    shipping_address = None
    if main_order_data['shipping_address']:
        try:
            shipping_address = ShippingAddress.model_validate_json(main_order_data['shipping_address'])
        except Exception as e:
            logger.error(f"Error parsing shipping address: {e}")
            # Continue without shipping address if parsing fails

    for record in order_records:
        order_out_items.append(OrderItemOut(
            order_item_id=record['order_item_id'],
            order_id=record['order_id'],
            product_id=record['product_id'],
            quantity=record['quantity'],
            total_price=record['item_total_price'],
            product_name=record['product_name'],
            product_image=record['product_image']
        ))

    order_out = OrderOut(
        order_id=main_order_data['order_id'],
        user_id=main_order_data['user_id'],
        shipping_address=shipping_address,
        payment_method=main_order_data['payment_method'],
        total_amount=main_order_data['total_amount'],
        status=main_order_data['status'],
        created_at=main_order_data['created_at'],
        updated_at=main_order_data['updated_at'],
        tracking_number=main_order_data['tracking_number'],
        estimated_delivery=main_order_data['estimated_delivery'],
        items=order_out_items
    )

    return order_out

@router.get("", response_model=List[OrderOut])
async def get_user_orders(
    current_user: UserOut = Depends(get_current_user)
):
    """Get all orders for the current user"""
    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()
        # Get all order IDs for the user first
        order_ids = await conn.fetch(
            "SELECT order_id FROM orders WHERE user_id = $1 ORDER BY created_at DESC",
            current_user.user_id
        )
        if not order_ids:
            return [] # Return empty list if no orders found

        # Fetch details for each order ID
        orders_list = []
        for record in order_ids:
            order_id = record['order_id']
            order_details = await fetch_order_details(conn, order_id, current_user.user_id)
            if order_details:
                orders_list.append(order_details)

        return orders_list

    except Exception as e:
        logger.error(f"Error getting user orders: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        if conn:
            await pool.release(conn)

@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Get a specific order by ID for the current user"""
    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()
        order_details = await fetch_order_details(conn, order_id, current_user.user_id)

        if not order_details:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found for this user"
            )

        return order_details

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting order {order_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        if conn:
            await pool.release(conn)

@router.put("/{order_id}", response_model=OrderOut)
async def update_order(
    order_id: int,
    order_update: OrderUpdate,
    current_user: UserOut = Depends(get_current_user)
):
    """Update an order (Admin only) - primarily for status and tracking"""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update orders"
        )

    pool = await get_pg_connection()
    conn = None
    try:
        conn = await pool.acquire()
        # Check if order exists
        order = await conn.fetchrow(
            "SELECT order_id FROM orders WHERE order_id = $1",
            order_id
        )
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )

        # Build update query dynamically based on provided fields
        update_fields = []
        params = []
        param_count = 1

        if order_update.status is not None:
            update_fields.append(f"status = ${param_count}")
            params.append(order_update.status)
            param_count += 1

        if order_update.tracking_number is not None:
            update_fields.append(f"tracking_number = ${param_count}")
            params.append(order_update.tracking_number)
            param_count += 1

        if order_update.estimated_delivery is not None:
            update_fields.append(f"estimated_delivery = ${param_count}")
            params.append(order_update.estimated_delivery)
            param_count += 1

        if not update_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        # Add updated_at timestamp and order_id to parameters
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(order_id)

        # Execute update
        update_query = f"""
            UPDATE orders
            SET {', '.join(update_fields)}
            WHERE order_id = ${param_count}
        """
        await conn.execute(update_query, *params)

        # Fetch the updated order with items for the response
        updated_order_details = await fetch_order_details(conn, order_id)

        # Re-check if order still exists after update (should if no error)
        if not updated_order_details:
             # This would be unusual, but for safety
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch updated order details")

        return updated_order_details

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating order {order_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        if conn:
            await pool.release(conn)

# Note: Delete endpoint is not included as it was not in the image or previous requests.
# Add it if needed. 

# Helper function to fetch product details including images
async def fetch_product_details(conn, product_id: int, user_id: Optional[int] = None):
    query = """
        SELECT
            p.product_id,
            p.seller_id,
            p.name,
            p.description,
            p.price,
            p.stock,
            p.category,
            p.rating,
            p.status,
            p.created_at,
            p.updated_at,
            p.product_type, -- Include product_type here
            COALESCE(json_agg(json_build_object(
                'image_id', pi.image_id,
                'image_url', pi.image_url,
                'uploaded_at', pi.uploaded_at
            ) ORDER BY pi.uploaded_at) FILTER (WHERE pi.image_id IS NOT NULL), '[]') as images_json
        FROM products p
        LEFT JOIN product_images pi ON p.product_id = pi.product_id
        WHERE p.product_id = $1
    """
    params = [product_id]

    # ... rest of the function ... 