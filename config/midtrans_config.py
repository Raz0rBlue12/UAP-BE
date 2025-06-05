import os
from dotenv import load_dotenv

load_dotenv()

# Midtrans Configuration
MIDTRANS_SERVER_KEY = os.getenv("MIDTRANS_SERVER_KEY")
MIDTRANS_CLIENT_KEY = os.getenv("MIDTRANS_CLIENT_KEY")
MIDTRANS_IS_PRODUCTION = os.getenv("MIDTRANS_IS_PRODUCTION", "false").lower() == "true"

# Payment Configuration
ALLOWED_PAYMENT_METHODS = [
    "bank_transfer",  # BCA, BNI, Mandiri
    "credit_card",
    "gopay",
    "shopeepay"
]

# Security Configuration
MINIMUM_AMOUNT = 10000  # Minimum transaction amount in IDR
MAXIMUM_AMOUNT = 10000000  # Maximum transaction amount in IDR
PAYMENT_TIMEOUT = 24 * 60 * 60  # 24 hours in seconds

# Notification URLs
NOTIFICATION_URL = os.getenv("MIDTRANS_NOTIFICATION_URL")  # Your backend notification endpoint
FINISH_REDIRECT_URL = os.getenv("MIDTRANS_FINISH_REDIRECT_URL")  # Frontend success page
UNFINISH_REDIRECT_URL = os.getenv("MIDTRANS_UNFINISH_REDIRECT_URL")  # Frontend pending page
ERROR_REDIRECT_URL = os.getenv("MIDTRANS_ERROR_REDIRECT_URL")  # Frontend error page 