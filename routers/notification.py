from fastapi import APIRouter, Depends, HTTPException, logger, status
from typing import List
from db.client import get_pg_connection
from models.notification import NotificationOut, NotificationCreate
from models.user import UserOut
from routers.auth import get_current_user
from datetime import datetime

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"]
)

@router.get("/me", response_model=List[NotificationOut])
async def get_user_notifications(current_user: UserOut = Depends(get_current_user)):
    """Get current user's notifications"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            query = """
                SELECT notification_id, user_id, message, is_read, created_at
                FROM notifications
                WHERE user_id = $1
                ORDER BY created_at DESC
            """
            rows = await conn.fetch(query, current_user.user_id)
            return [dict(row) for row in rows]
    finally:
        await pool.close()

@router.put("/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_as_read(
    notification_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Mark a notification as read"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if notification exists and belongs to user
            check_query = """
                SELECT * FROM notifications 
                WHERE notification_id = $1 AND user_id = $2
            """
            notification = await conn.fetchrow(check_query, notification_id, current_user.user_id)
            if not notification:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Notification not found"
                )
            
            # Update notification
            update_query = """
                UPDATE notifications 
                SET is_read = true 
                WHERE notification_id = $1
                RETURNING notification_id, user_id, message, is_read, created_at
            """
            updated = await conn.fetchrow(update_query, notification_id)
            return dict(updated)
    finally:
        await pool.close()

@router.put("/read-all", response_model=dict)
async def mark_all_notifications_as_read(current_user: UserOut = Depends(get_current_user)):
    """Mark all notifications as read"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            update_query = """
                UPDATE notifications 
                SET is_read = true 
                WHERE user_id = $1 AND is_read = false
            """
            await conn.execute(update_query, current_user.user_id)
            return {"message": "All notifications marked as read"}
    finally:
        await pool.close()

@router.delete("/{notification_id}", response_model=dict)
async def delete_notification(
    notification_id: int,
    current_user: UserOut = Depends(get_current_user)
):
    """Delete a notification"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if notification exists and belongs to user
            check_query = """
                SELECT * FROM notifications 
                WHERE notification_id = $1 AND user_id = $2
            """
            notification = await conn.fetchrow(check_query, notification_id, current_user.user_id)
            if not notification:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Notification not found"
                )
            
            # Delete notification
            delete_query = """
                DELETE FROM notifications 
                WHERE notification_id = $1
            """
            await conn.execute(delete_query, notification_id)
            return {"message": "Notification successfully deleted"}
    finally:
        await pool.close()

# Internal function to create a notification (can be called by other services)
async def create_notification(
    user_id: int,
    message: str
):
    """Create a new notification for a user"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
             new_notification = await conn.fetchrow(
                "INSERT INTO notifications (user_id, message) VALUES ($1, $2) RETURNING notification_id, user_id, message, is_read, created_at",
                user_id, message
            )
             return NotificationOut(**dict(new_notification))
    except Exception as e:
        logger.error(f"Error creating notification for user {user_id}: {str(e)}", exc_info=True) # Assuming logger is available
        return None # Indicate failure
    finally:
        await pool.close() 