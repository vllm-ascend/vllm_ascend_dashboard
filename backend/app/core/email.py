"""
SMTP 邮件发送工具（异步）

支持两种 TLS 模式：
- Port 465: 隐式 TLS (SMTPS)，连接即加密
- Port 587: 显式 STARTTLS，先明文连接再升级加密
"""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

logger = logging.getLogger(__name__)


async def send_email(
    subject: str,
    html_content: str,
    recipients: list[str],
    cc_recipients: list[str] | None = None,
    smtp_host: str = "",
    smtp_port: int = 587,
    smtp_username: str = "",
    smtp_password: str = "",
    smtp_use_tls: bool = True,
    from_email: str = "",
) -> dict:
    if not smtp_host:
        return {"success": False, "error": "SMTP_HOST not configured"}

    if not recipients:
        return {"success": False, "error": "No recipients configured"}

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = ", ".join(recipients)
    if cc_recipients:
        msg["Cc"] = ", ".join(cc_recipients)

    html_part = MIMEText(html_content, "html", "utf-8")
    msg.attach(html_part)

    all_recipients = recipients + (cc_recipients or [])

    use_implicit_tls = smtp_use_tls and smtp_port == 465
    use_starttls = smtp_use_tls and smtp_port != 465

    try:
        smtp_client = aiosmtplib.SMTP(
            hostname=smtp_host,
            port=smtp_port,
            use_tls=use_implicit_tls,
        )

        await smtp_client.connect()

        if use_starttls:
            await smtp_client.starttls(validate_certs=False)

        await smtp_client.login(smtp_username, smtp_password)
        await smtp_client.send_message(msg)
        await smtp_client.quit()

        logger.info(f"Email sent successfully to {all_recipients}")
        return {"success": True, "error": None}

    except Exception as e:
        logger.error(f"Failed to send email: {e}", exc_info=True)
        return {"success": False, "error": str(e)}