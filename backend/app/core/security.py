"""
安全工具模块
"""
import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    """密码加密"""
    password_bytes = password.encode('utf-8')
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    try:
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except ValueError as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"Password verification error: {e}")
        return False
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error during password verification: {e}")
        return False


def anonymize_ip(ip_address: str) -> str:
    """IP 地址匿名化：将最后一段替换为 0"""
    if not ip_address:
        return ""
    parts = ip_address.split('.')
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.0"
    if ':' in ip_address:
        segments = ip_address.split(':')
        if len(segments) >= 4:
            return ':'.join(segments[:4]) + ':0:0:0:0'
    return hashlib.sha256(ip_address.encode()).hexdigest()[:16]


def hash_ip(ip_address: str) -> str:
    """IP 地址哈希化，用于统计比对"""
    if not ip_address:
        return ""
    return hashlib.sha256(ip_address.encode()).hexdigest()


def create_access_token(
    data: dict,
    expires_delta: timedelta | None = None
) -> str:
    """生成访问 Token"""
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire, "iat": datetime.now(UTC), "jti": str(uuid.uuid4())})

    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM
    )

    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """生成刷新 Token（7 天有效期）"""
    return create_access_token(data, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str) -> dict | None:
    """解码 Token"""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except ExpiredSignatureError:
        return None
    except JWTError as e:
        logger = logging.getLogger(__name__)
        logger.warning(f"JWT decode error: {e}, token: {token[:20]}...")
        return None
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error during token decoding: {e}")
        return None
