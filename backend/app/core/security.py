import hashlib
import logging
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import ExpiredSignatureError, JWTError, jwt

from app.core.config import settings

_logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except ValueError as e:
        _logger.warning(f"Password verification error: {e}")
        return False
    except Exception as e:
        _logger.error(f"Unexpected error during password verification: {e}")
        return False


def anonymize_ip(ip_address: str) -> str:
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
    if not ip_address:
        return ""
    return hashlib.sha256(ip_address.encode()).hexdigest()


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.now(UTC), "jti": str(uuid.uuid4())})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(data: dict) -> str:
    return create_access_token(data, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except ExpiredSignatureError:
        return None
    except JWTError as e:
        _logger.warning(f"JWT decode error: {e}, token: {token[:20]}...")
        return None
    except Exception as e:
        _logger.error(f"Unexpected error during token decoding: {e}")
        return None
