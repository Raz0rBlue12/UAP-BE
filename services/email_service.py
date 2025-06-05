import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config.email_config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    SMTP_FROM_EMAIL,
    RESET_PASSWORD_TEMPLATE
)
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def send_reset_password_email(email: str, username: str, reset_token: str, frontend_url: str):
    """Send reset password email to user"""
    try:
        logger.debug(f"Attempting to send email to {email}")
        logger.debug(f"SMTP Configuration: Host={SMTP_HOST}, Port={SMTP_PORT}, User={SMTP_USER}")

        # Create message
        message = MIMEMultipart()
        message["From"] = SMTP_FROM_EMAIL
        message["To"] = email
        message["Subject"] = "Reset Your Password"

        # Create reset link
        reset_link = f"{frontend_url}/reset-password?token={reset_token}"
        logger.debug(f"Reset link: {reset_link}")

        # Create HTML content
        html_content = RESET_PASSWORD_TEMPLATE.format(
            username=username,
            reset_link=reset_link
        )

        # Attach HTML content
        message.attach(MIMEText(html_content, "html"))

        # Send email
        logger.debug("Connecting to SMTP server...")
        try:
            # Try TLS first
            async with aiosmtplib.SMTP(
                hostname=SMTP_HOST,
                port=SMTP_PORT,
                use_tls=True
            ) as smtp:
                logger.debug("Connected to SMTP server with TLS, attempting login...")
                await smtp.login(SMTP_USER, SMTP_PASSWORD)
                logger.debug("Login successful, sending message...")
                await smtp.send_message(message)
                logger.debug("Message sent successfully")
        except Exception as tls_error:
            logger.warning(f"TLS connection failed: {str(tls_error)}, trying without TLS...")
            # If TLS fails, try without encryption
            async with aiosmtplib.SMTP(
                hostname=SMTP_HOST,
                port=SMTP_PORT
            ) as smtp:
                logger.debug("Connected to SMTP server without encryption, attempting login...")
                await smtp.login(SMTP_USER, SMTP_PASSWORD)
                logger.debug("Login successful, sending message...")
                await smtp.send_message(message)
                logger.debug("Message sent successfully")

        return True
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}", exc_info=True)
        return False 