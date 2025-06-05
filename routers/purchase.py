from fastapi import APIRouter, HTTPException, status, Depends, Query
from typing import List, Optional
from datetime import datetime
from decimal import Decimal
from db.client import get_pg_connection
from models.purchase import PurchaseCreate, PurchaseOut, PurchaseUpdate
from routers.auth import get_current_user, require_role
from utils.rate_limiter import RateLimiter

router = APIRouter(
    prefix="/purchases",
    tags=["Purchases"]
)

@router.post("/", response_model=PurchaseOut)
async def create_purchase(
    purchase: PurchaseCreate,
    current_user = Depends(get_current_user),
    rate_limiter: RateLimiter = Depends(RateLimiter(limit=10, window=60))  # 10 requests per minute
):
    """Create a new purchase"""
    conn = await get_pg_connection()
    try:
        async with conn.transaction():
            # Create purchase record
            purchase_record = await conn.fetchrow(
                """
                INSERT INTO purchases (
                    user_id, shipping_address, payment_method, 
                    total_amount, status, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, 'pending', NOW(), NOW())
                RETURNING purchase_id, user_id, shipping_address, payment_method, 
                          total_amount, status, created_at, updated_at
                """,
                current_user["user_id"],
                purchase.shipping_address,
                purchase.payment_method,
                purchase.total_amount
            )

            # Insert purchase items
            for item in purchase.items:
                await conn.execute(
                    """
                    INSERT INTO purchase_items (
                        purchase_id, product_id, quantity, price
                    )
                    VALUES ($1, $2, $3, $4)
                    """,
                    purchase_record["purchase_id"],
                    item.product_id,
                    item.quantity,
                    item.price
                )

                # Update product stock
                await conn.execute(
                    """
                    UPDATE products
                    SET stock = stock - $1
                    WHERE product_id = $2
                    """,
                    item.quantity,
                    item.product_id
                )

            # Fetch complete purchase details
            complete_purchase = await conn.fetchrow(
                """
                SELECT 
                    p.*,
                    json_agg(
                        json_build_object(
                            'product_id', pi.product_id,
                            'quantity', pi.quantity,
                            'price', pi.price,
                            'product_name', pr.name,
                            'product_image', pr.image_url
                        )
                    ) as items
                FROM purchases p
                JOIN purchase_items pi ON p.purchase_id = pi.purchase_id
                JOIN products pr ON pi.product_id = pr.product_id
                WHERE p.purchase_id = $1
                GROUP BY p.purchase_id
                """,
                purchase_record["purchase_id"]
            )

            return dict(complete_purchase)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await conn.close()

@router.get("/", response_model=List[PurchaseOut])
async def get_purchases(
    current_user = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    rate_limiter: RateLimiter = Depends(RateLimiter(limit=100, window=60))
):
    """Get user's purchase history with optional filtering"""
    conn = await get_pg_connection()
    try:
        query = """
            SELECT 
                p.*,
                json_agg(
                    json_build_object(
                        'product_id', pi.product_id,
                        'quantity', pi.quantity,
                        'price', pi.price,
                        'product_name', pr.name,
                        'product_image', pr.image_url
                    )
                ) as items
            FROM purchases p
            JOIN purchase_items pi ON p.purchase_id = pi.purchase_id
            JOIN products pr ON pi.product_id = pr.product_id
            WHERE p.user_id = $1
        """
        params = [current_user["user_id"]]
        
        if status:
            query += " AND p.status = $2"
            params.append(status)
            
        query += """
            GROUP BY p.purchase_id
            ORDER BY p.created_at DESC
            LIMIT $3 OFFSET $4
        """
        params.extend([limit, skip])

        purchases = await conn.fetch(query, *params)
        return [dict(purchase) for purchase in purchases]

    finally:
        await conn.close()

@router.get("/{purchase_id}", response_model=PurchaseOut)
async def get_purchase(
    purchase_id: int,
    current_user = Depends(get_current_user),
    rate_limiter: RateLimiter = Depends(RateLimiter(limit=100, window=60))
):
    """Get detailed information about a specific purchase"""
    conn = await get_pg_connection()
    try:
        purchase = await conn.fetchrow(
            """
            SELECT 
                p.*,
                json_agg(
                    json_build_object(
                        'product_id', pi.product_id,
                        'quantity', pi.quantity,
                        'price', pi.price,
                        'product_name', pr.name,
                        'product_image', pr.image_url
                    )
                ) as items
            FROM purchases p
            JOIN purchase_items pi ON p.purchase_id = pi.purchase_id
            JOIN products pr ON pi.product_id = pr.product_id
            WHERE p.purchase_id = $1 AND p.user_id = $2
            GROUP BY p.purchase_id
            """,
            purchase_id,
            current_user["user_id"]
        )

        if not purchase:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase not found"
            )

        return dict(purchase)

    finally:
        await conn.close()

@router.patch("/{purchase_id}", response_model=PurchaseOut)
async def update_purchase_status(
    purchase_id: int,
    update: PurchaseUpdate,
    current_user = Depends(require_role(["admin", "seller"])),
    rate_limiter: RateLimiter = Depends(RateLimiter(limit=50, window=60))
):
    """Update purchase status (admin/seller only)"""
    conn = await get_pg_connection()
    try:
        # Check if purchase exists
        purchase = await conn.fetchrow(
            "SELECT * FROM purchases WHERE purchase_id = $1",
            purchase_id
        )
        if not purchase:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Purchase not found"
            )

        # Build update query dynamically based on provided fields
        update_fields = []
        params = []
        param_index = 1

        if update.status is not None:
            update_fields.append(f"status = ${param_index}")
            params.append(update.status)
            param_index += 1

        if update.tracking_number is not None:
            update_fields.append(f"tracking_number = ${param_index}")
            params.append(update.tracking_number)
            param_index += 1

        if update.estimated_delivery is not None:
            update_fields.append(f"estimated_delivery = ${param_index}")
            params.append(update.estimated_delivery)
            param_index += 1

        if not update_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )

        update_fields.append("updated_at = NOW()")
        params.append(purchase_id)

        # Execute update
        updated_purchase = await conn.fetchrow(
            f"""
            UPDATE purchases
            SET {', '.join(update_fields)}
            WHERE purchase_id = ${param_index}
            RETURNING *
            """,
            *params
        )

        # Fetch complete purchase details
        complete_purchase = await conn.fetchrow(
            """
            SELECT 
                p.*,
                json_agg(
                    json_build_object(
                        'product_id', pi.product_id,
                        'quantity', pi.quantity,
                        'price', pi.price,
                        'product_name', pr.name,
                        'product_image', pr.image_url
                    )
                ) as items
            FROM purchases p
            JOIN purchase_items pi ON p.purchase_id = pi.purchase_id
            JOIN products pr ON pi.product_id = pr.product_id
            WHERE p.purchase_id = $1
            GROUP BY p.purchase_id
            """,
            purchase_id
        )

        return dict(complete_purchase)

    finally:
        await conn.close() 