"""
认证 API 路由
"""
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, get_current_user
from app.core.security import (
    anonymize_ip, create_access_token, create_refresh_token,
    decode_token, hash_ip, hash_password, verify_password,
)
from app.models import User, UserLoginLog, TokenBlacklist
from app.schemas import LoginRequest, Message, PasswordChange, RegisterRequest, Token, UserResponse
from app.services.rate_limiter import check_rate_limit

router = APIRouter()
logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, db: DbSession, data: RegisterRequest):
    ip = _client_ip(request)
    try:
        check_rate_limit(ip, "register")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    user = User(username=data.username, email=data.email, password_hash=hash_password(data.password), role="user", is_active=True)
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="注册信息已被使用，请更换用户名或邮箱")
    except Exception as e:
        await db.rollback()
        logger.error(f"Registration failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="注册失败，请稍后重试")
    logger.info(f"New user registered: {user.username} from IP {anonymize_ip(ip)}")
    return user


@router.post("/login", response_model=Token)
async def login(request: Request, db: DbSession, data: LoginRequest):
    ip = _client_ip(request)
    try:
        check_rate_limit(ip, "login")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))

    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="用户账号已被禁用")

    ip = _client_ip(request)
    try:
        db.add(UserLoginLog(user_id=user.id, ip_address=anonymize_ip(ip), ip_address_hashed=hash_ip(ip), user_agent=request.headers.get("User-Agent", "")[:500], login_method="password"))
        await db.commit()
    except Exception as e:
        logger.warning(f"Failed to log login event: {e}")
        await db.rollback()

    return {"access_token": create_access_token(data={"sub": user.username, "user_id": user.id, "role": user.role}), "refresh_token": create_refresh_token(data={"sub": user.username, "user_id": user.id, "role": user.role}), "token_type": "bearer", "expires_in": 86400}


@router.post("/logout", response_model=Message)
async def logout(request: Request, db: DbSession, current_user: User = Depends(get_current_user)):
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        payload = decode_token(auth_header.split(" ")[1])
        if payload:
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti:
                try:
                    db.add(TokenBlacklist(token_jti=jti, expires_at=datetime.fromtimestamp(exp, UTC) if exp else datetime.now(UTC) + timedelta(days=1)))
                    await db.commit()
                except Exception as e:
                    logger.warning(f"Failed to blacklist token on logout: {e}")
                    await db.rollback()
    return {"message": "已成功登出"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/refresh", response_model=Token)
async def refresh_token(request: Request, db: DbSession):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少刷新Token")
    payload = decode_token(auth_header.split(" ")[1])
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新Token无效或已过期")

    jti = payload.get("jti")
    if jti:
        try:
            blacklist_result = await db.execute(select(TokenBlacklist).where(TokenBlacklist.token_jti == jti))
            if blacklist_result.scalar_one_or_none():
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token已被撤销")
        except Exception as e:
            logger.warning(f"Token blacklist check failed, skipping: {e}")

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新Token无效")
    user_result = await db.execute(select(User).where(User.username == username))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被禁用")

    return {"access_token": create_access_token(data={"sub": username, "user_id": user.id, "role": user.role}), "refresh_token": create_refresh_token(data={"sub": username, "user_id": user.id, "role": user.role}), "token_type": "bearer", "expires_in": 86400}


@router.post("/change-password", response_model=Message)
async def change_password(db: DbSession, data: PasswordChange, current_user: User = Depends(get_current_user)):
    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
    current_user.password_hash = hash_password(data.new_password)
    await db.commit()
    return {"message": "密码已成功修改"}
