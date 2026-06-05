"""
SMTP 邮件发送工具（异步）
"""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_email(
    subject: str,
    html_content: str,
    recipients: list[str],
    cc_recipients: list[str] | None = None,
) -> dict:
    """
    异步发送 HTML 邮件

    Returns:
        {"success": True/False, "error": str | None}
    """
    if not settings.SMTP_HOST:
        return {"success": False, "error": "SMTP_HOST not configured"}

    if not recipients:
        return {"success": False, "error": "No recipients configured"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.REPORT_FROM_EMAIL
    msg["To"] = ", ".join(recipients)
    if cc_recipients:
        msg["Cc"] = ", ".join(cc_recipients)

    html_part = MIMEText(html_content, "html", "utf-8")
    msg.attach(html_part)

    all_recipients = recipients + (cc_recipients or [])

    try:
        if settings.SMTP_USE_TLS:
            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME,
                password=settings.SMTP_PASSWORD,
                start_tls=True,
            )
        else:
            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USERNAME,
                password=settings.SMTP_PASSWORD,
                use_tls=False,
            )

        logger.info(f"Email sent successfully to {all_recipients}")
        return {"success": True, "error": None}

    except Exception as e:
        logger.error(f"Failed to send email: {e}", exc_info=True)
        return {"success": False, "error": str(e)}