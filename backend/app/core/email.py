"""
SMTP 邮件发送工具（异步）
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
    """
    异步发送 HTML 邶件

    Args:
        subject: 邶件主题
        html_content: HTML 内容
        recipients: 收件人列表
        cc_recipients: 抄送人列表
        smtp_host: SMTP 服务器地址
        smtp_port: SMTP 端口
        smtp_username: SMTP 用户名
        smtp_password: SMTP 密码
        smtp_use_tls: 是否启用 TLS
        from_email: 发件人地址

    Returns:
        {"success": True/False, "error": str | None}
    """
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

    try:
        if smtp_use_tls:
            use_implicit_tls = smtp_port == 465
            await aiosmtplib.send(
                msg,
                hostname=smtp_host,
                port=smtp_port,
                username=smtp_username,
                password=smtp_password,
                use_tls=use_implicit_tls,
                start_tls=not use_implicit_tls,
            )
        else:
            await aiosmtplib.send(
                msg,
                hostname=smtp_host,
                port=smtp_port,
                username=smtp_username,
                password=smtp_password,
                use_tls=False,
            )

        logger.info(f"Email sent successfully to {all_recipients}")
        return {"success": True, "error": None}

    except Exception as e:
        logger.error(f"Failed to send email: {e}", exc_info=True)
        return {"success": False, "error": str(e)}