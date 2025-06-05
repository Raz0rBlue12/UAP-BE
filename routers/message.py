from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List
from db.client import get_pg_connection
from models.message import MessageCreate, MessageOut
from routers.auth import get_current_user

router = APIRouter(
    prefix="/messages",
    tags=["Messages"]
)

@router.post("/", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def create_message(
    message: MessageCreate,
    current_user = Depends(get_current_user)
):
    """Send a new message"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Ensure receiver exists
                receiver_exists = await conn.fetchrow(
                    "SELECT user_id FROM users WHERE user_id = $1",
                    message.receiver_id
                )
                if not receiver_exists:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Receiver user not found"
                    )

                new_message = await conn.fetchrow(
                    """
                    INSERT INTO messages (sender_id, receiver_id, content)
                    VALUES ($1, $2, $3)
                    RETURNING message_id, sender_id, receiver_id, content, sent_at, is_read
                    """,
                    current_user['user_id'],
                    message.receiver_id,
                    message.content
                )

                if not new_message:
                     raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to send message"
                    )

                return MessageOut(**dict(new_message))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

@router.get("/{other_user_id}", response_model=List[MessageOut])
async def get_messages(
    other_user_id: int,
    current_user = Depends(get_current_user),
    limit: int = Query(100, description="Limit the number of messages", ge=1, le=200),
    offset: int = Query(0, description="Offset for pagination", ge=0)
):
    """Get messages between the current user and another user"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
            # Select messages where sender is current user and receiver is other_user_id
            # OR sender is other_user_id and receiver is current user
            messages = await conn.fetch(
                """
                SELECT message_id, sender_id, receiver_id, content, sent_at, is_read
                FROM messages
                WHERE (sender_id = $1 AND receiver_id = $2)
                   OR (sender_id = $2 AND receiver_id = $1)
                ORDER BY sent_at ASC
                LIMIT $3 OFFSET $4
                """,
                current_user['user_id'],
                other_user_id,
                limit,
                offset
            )

            # Optionally mark messages sent TO the current user as read
            # if messages:
            #     messages_to_mark_read = [msg['message_id'] for msg in messages if msg['receiver_id'] == current_user['user_id'] and not msg['is_read']]
            #     if messages_to_mark_read:
            #         await conn.execute(
            #             "UPDATE messages SET is_read = TRUE WHERE message_id = ANY($1)",
            #             messages_to_mark_read
            #         )

            return [MessageOut(**dict(msg)) for msg in messages]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close()

# Optional: Endpoint to mark a specific message as read
@router.put("/{message_id}/read", response_model=MessageOut)
async def mark_message_as_read(
    message_id: int,
    current_user = Depends(get_current_user)
):
    """Mark a specific message as read (only if current user is the receiver)"""
    pool = await get_pg_connection()
    try:
        async with pool.acquire() as conn:
             async with conn.transaction():
                # Check if message exists and current user is the receiver
                message = await conn.fetchrow(
                    "SELECT message_id, receiver_id FROM messages WHERE message_id = $1",
                    message_id
                )
                if not message:
                     raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Message not found"
                    )

                if message['receiver_id'] != current_user['user_id']:
                     raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Not authorized to mark this message as read"
                    )

                # Mark as read
                updated_message = await conn.fetchrow(
                    """
                    UPDATE messages
                    SET is_read = TRUE
                    WHERE message_id = $1 AND receiver_id = $2
                    RETURNING message_id, sender_id, receiver_id, content, sent_at, is_read
                    """,
                    message_id,
                    current_user['user_id']
                )

                if not updated_message:
                     # This case should ideally not happen if the message exists and user is receiver
                     raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to mark message as read"
                    )

                return MessageOut(**dict(updated_message))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    finally:
        await pool.close() 