from fastapi import APIRouter, Depends, HTTPException, logger, status
from typing import List
from db.client import get_pg_connection
from models.notification import NotificationOut, NotificationCreate
from routers.auth import get_current_user

router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"]
)

# Endpoint to get notifications for the current user
@router.get("/me", response_model=List[NotificationOut])
async def get_my_notifications(
    current_user = Depends(get_current_user)
):
    """Get notifications for the authenticated user"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            notifications = await conn.fetch(
                "SELECT notification_id, user_id, message, is_read, created_at FROM notifications WHERE user_id = $1 ORDER BY created_at DESC",
                current_user['user_id']
            )
            return [NotificationOut(**dict(n)) for n in notifications]
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
    finally:
        await pool.close()

# Endpoint to mark a notification as read
@router.put("/{notification_id}/read", response_model=NotificationOut)
async def mark_notification_as_read(
    notification_id: int,
    current_user = Depends(get_current_user)
):
    """Mark a specific notification as read"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Check if notification exists and belongs to the user
            existing_notification = await conn.fetchrow(
                "SELECT notification_id, user_id FROM notifications WHERE notification_id = $1 AND user_id = $2",
                notification_id, current_user['user_id']
            )
            if not existing_notification:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found or does not belong to user")

            # Mark as read
            updated_notification = await conn.fetchrow(
                "UPDATE notifications SET is_read = TRUE WHERE notification_id = $1 RETURNING notification_id, user_id, message, is_read, created_at",
                notification_id
            )
            return NotificationOut(**dict(updated_notification))
    except HTTPException:
        raise # Re-raise HTTP exceptions
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
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