import hashlib
import hmac
import json
import time
from typing import Dict, Optional
import aiohttp
from fastapi import HTTPException, status
from config.midtrans_config import (
    MIDTRANS_SERVER_KEY,
    MIDTRANS_CLIENT_KEY,
    MIDTRANS_IS_PRODUCTION,
    ALLOWED_PAYMENT_METHODS,
    MINIMUM_AMOUNT,
    MAXIMUM_AMOUNT,
    PAYMENT_TIMEOUT,
    NOTIFICATION_URL,
    FINISH_REDIRECT_URL,
    UNFINISH_REDIRECT_URL,
    ERROR_REDIRECT_URL
)

class PaymentService:
    def __init__(self):
        self.base_url = "https://api.midtrans.com/v2" if MIDTRANS_IS_PRODUCTION else "https://api.sandbox.midtrans.com/v2"
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Basic {MIDTRANS_SERVER_KEY}"
        }

    def _validate_amount(self, amount: int) -> None:
        """Validate transaction amount"""
        if amount < MINIMUM_AMOUNT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Amount must be at least {MINIMUM_AMOUNT}"
            )
        if amount > MAXIMUM_AMOUNT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Amount cannot exceed {MAXIMUM_AMOUNT}"
            )

    def _validate_payment_method(self, payment_method: str) -> None:
        """Validate payment method"""
        if payment_method not in ALLOWED_PAYMENT_METHODS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid payment method. Allowed methods: {', '.join(ALLOWED_PAYMENT_METHODS)}"
            )

    def _generate_order_id(self, user_id: int) -> str:
        """Generate unique order ID with timestamp and user ID"""
        timestamp = int(time.time())
        return f"ORDER-{user_id}-{timestamp}"

    def _create_signature(self, order_id: str, status_code: str, gross_amount: str) -> str:
        """Create signature for notification verification"""
        message = f"{order_id}{status_code}{gross_amount}{MIDTRANS_SERVER_KEY}"
        signature = hmac.new(
            MIDTRANS_SERVER_KEY.encode(),
            message.encode(),
            hashlib.sha512
        ).hexdigest()
        return signature

    async def create_transaction(
        self,
        user_id: int,
        amount: int,
        payment_method: str,
        customer_details: Dict,
        item_details: list
    ) -> Dict:
        """Create a new transaction"""
        try:
            # Validate inputs
            self._validate_amount(amount)
            self._validate_payment_method(payment_method)

            # Generate order ID
            order_id = self._generate_order_id(user_id)

            # Prepare transaction data
            transaction_data = {
                "transaction_details": {
                    "order_id": order_id,
                    "gross_amount": amount
                },
                "customer_details": customer_details,
                "item_details": item_details,
                "payment_type": payment_method,
                "expiry": {
                    "start_time": time.strftime("%Y-%m-%d %H:%M:%S +0700"),
                    "unit": "hour",
                    "duration": 24
                },
                "callbacks": {
                    "finish": FINISH_REDIRECT_URL,
                    "unfinish": UNFINISH_REDIRECT_URL,
                    "error": ERROR_REDIRECT_URL
                }
            }

            # Add payment-specific details
            if payment_method == "bank_transfer":
                transaction_data["bank_transfer"] = {
                    "bank": "bca"  # Default to BCA, can be made configurable
                }
            elif payment_method == "credit_card":
                transaction_data["credit_card"] = {
                    "secure": True,
                    "bank": "all",
                    "installment": {
                        "required": False,
                        "terms": {
                            "bca": [3, 6, 12],
                            "bni": [3, 6, 12],
                            "mandiri": [3, 6, 12]
                        }
                    }
                }

            # Make API request to Midtrans
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/charge",
                    headers=self.headers,
                    json=transaction_data
                ) as response:
                    if response.status != 201:
                        error_data = await response.json()
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Payment gateway error: {error_data.get('message', 'Unknown error')}"
                        )
                    
                    result = await response.json()
                    return result

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error creating transaction: {str(e)}"
            )

    async def verify_notification(self, notification_data: Dict) -> bool:
        """Verify Midtrans notification signature"""
        try:
            order_id = notification_data.get("order_id")
            status_code = notification_data.get("status_code")
            gross_amount = notification_data.get("gross_amount")
            signature = notification_data.get("signature_key")

            if not all([order_id, status_code, gross_amount, signature]):
                return False

            expected_signature = self._create_signature(
                order_id,
                status_code,
                str(gross_amount)
            )

            return hmac.compare_digest(signature, expected_signature)

        except Exception:
            return False

    async def get_transaction_status(self, order_id: str) -> Dict:
        """Get transaction status from Midtrans"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/{order_id}/status",
                    headers=self.headers
                ) as response:
                    if response.status != 200:
                        error_data = await response.json()
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Error getting transaction status: {error_data.get('message', 'Unknown error')}"
                        )
                    
                    return await response.json()

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error getting transaction status: {str(e)}"
            )

    async def cancel_transaction(self, order_id: str) -> Dict:
        """Cancel a transaction"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/{order_id}/cancel",
                    headers=self.headers
                ) as response:
                    if response.status != 200:
                        error_data = await response.json()
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Error canceling transaction: {error_data.get('message', 'Unknown error')}"
                        )
                    
                    return await response.json()

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error canceling transaction: {str(e)}"
            ) 