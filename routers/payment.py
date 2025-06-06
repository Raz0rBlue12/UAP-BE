from fastapi import APIRouter, HTTPException, status, Depends, Request, Response
from typing import Dict, List
from pydantic import BaseModel
from datetime import datetime
from db.client import get_pg_connection
from routers.auth import get_current_user, require_role
from services.payment_service import PaymentService
from utils.rate_limiter import RateLimiter

router = APIRouter(
    prefix="/payments",
    tags=["Payments"]
)

payment_service = PaymentService()

class PaymentRequest(BaseModel):
    amount: int
    payment_method: str
    customer_details: Dict
    item_details: List[Dict]

class PaymentResponse(BaseModel):
    order_id: str
    payment_url: str
    status: str
    created_at: datetime

@router.post("/create", response_model=PaymentResponse)
async def create_payment(
    payment: PaymentRequest,
    current_user = Depends(get_current_user),
    rate_limiter: RateLimiter = Depends(RateLimiter(limit=10, window=60))
):
    """Create a new payment transaction"""
    conn = await get_pg_connection()
    try:
        # Create transaction in Midtrans
        transaction = await payment_service.create_transaction(
            user_id=current_user.user_id,
            amount=payment.amount,
            payment_method=payment.payment_method,
            customer_details=payment.customer_details,
            item_details=payment.item_details
        )

        # Store transaction in database
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO payment_transactions (
                    order_id, user_id, amount, payment_method,
                    status, payment_url, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, NOW(), NOW())
                """,
                transaction["order_id"],
                current_user.user_id,
                payment.amount,
                payment.payment_method,
                transaction["transaction_status"],
                transaction.get("redirect_url", "")
            )

        return PaymentResponse(
            order_id=transaction["order_id"],
            payment_url=transaction.get("redirect_url", ""),
            status=transaction["transaction_status"],
            created_at=datetime.now()
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await conn.close()

@router.post("/notification")
async def payment_notification(request: Request):
    """Handle Midtrans payment notification"""
    try:
        # Get notification data
        notification_data = await request.json()
        
        # Verify signature
        if not await payment_service.verify_notification(notification_data):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid signature"
            )

        conn = await get_pg_connection()
        try:
            async with conn.transaction():
                # Update transaction status
                await conn.execute(
                    """
                    UPDATE payment_transactions
                    SET 
                        status = $1,
                        updated_at = NOW(),
                        payment_details = $2
                    WHERE order_id = $3
                    """,
                    notification_data["transaction_status"],
                    notification_data,
                    notification_data["order_id"]
                )

                # If payment is successful, update purchase status
                if notification_data["transaction_status"] == "settlement":
                    await conn.execute(
                        """
                        UPDATE purchases
                        SET 
                            status = 'paid',
                            updated_at = NOW()
                        WHERE order_id = $1
                        """,
                        notification_data["order_id"]
                    )

        finally:
            await conn.close()

        return {"status": "OK"}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/status/{order_id}")
async def get_payment_status(
    order_id: str,
    current_user = Depends(get_current_user),
    rate_limiter: RateLimiter = Depends(RateLimiter(limit=100, window=60))
):
    """Get payment status"""
    conn = await get_pg_connection()
    try:
        # Get transaction from database
        transaction = await conn.fetchrow(
            """
            SELECT * FROM payment_transactions
            WHERE order_id = $1 AND user_id = $2
            """,
            order_id,
            current_user.user_id
        )

        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )

        # Get latest status from Midtrans
        midtrans_status = await payment_service.get_transaction_status(order_id)

        # Update status in database if different
        if midtrans_status["transaction_status"] != transaction["status"]:
            await conn.execute(
                """
                UPDATE payment_transactions
                SET 
                    status = $1,
                    updated_at = NOW(),
                    payment_details = $2
                WHERE order_id = $3
                """,
                midtrans_status["transaction_status"],
                midtrans_status,
                order_id
            )

        return {
            "order_id": order_id,
            "status": midtrans_status["transaction_status"],
            "amount": transaction["amount"],
            "payment_method": transaction["payment_method"],
            "created_at": transaction["created_at"],
            "updated_at": transaction["updated_at"]
        }

    finally:
        await conn.close()

@router.post("/cancel/{order_id}")
async def cancel_payment(
    order_id: str,
    current_user = Depends(get_current_user),
    rate_limiter: RateLimiter = Depends(RateLimiter(limit=5, window=60))
):
    """Cancel a payment"""
    conn = await get_pg_connection()
    try:
        # Check if transaction exists and belongs to user
        transaction = await conn.fetchrow(
            """
            SELECT * FROM payment_transactions
            WHERE order_id = $1 AND user_id = $2
            """,
            order_id,
            current_user.user_id
        )

        if not transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Transaction not found"
            )

        if transaction["status"] not in ["pending", "challenge"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot cancel transaction in current status"
            )

        # Cancel in Midtrans
        result = await payment_service.cancel_transaction(order_id)

        # Update status in database
        await conn.execute(
            """
            UPDATE payment_transactions
            SET 
                status = 'cancelled',
                updated_at = NOW(),
                payment_details = $1
            WHERE order_id = $2
            """,
            result,
            order_id
        )

        return {"status": "cancelled", "message": "Payment cancelled successfully"}

    finally:
        await conn.close() 