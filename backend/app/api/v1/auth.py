"""
认证 API 路由
"""
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy import select, func

from app.api.deps import DbSession, get_current_user
from app.core.security import (
    anonymize_ip,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_ip,
    hash_password,
    verify_password,
)
from app.models import User, UserLoginLog, TokenBlacklist
from app.schemas import (
    LoginRequest,
    Message,
    PasswordChange,
    RegisterRequest,
    Token,
    UserResponse,
)
from app.services.rate_limiter import check_rate_limit

router = APIRouter()
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    db: DbSession,
    register_data: RegisterRequest,
):
    """用户自助注册"""
    client_ip = _get_client_ip(request)

    try:
        check_rate_limit(client_ip, "register")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(e),
        )

    stmt = select(User).where(User.username == register_data.username)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在",
        )

    stmt = select(User).where(User.email == register_data.email)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邮箱已被注册",
        )

    user = User(
        username=register_data.username,
        email=register_data.email,
        password_hash=hash_password(register_data.password),
        role="user",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(f"New user registered: {user.username} from IP {anonymize_ip(client_ip)}")
    return user


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    db: DbSession,
    login_data: LoginRequest,
):
    """用户登录"""
    stmt = select(User).where(User.username == login_data.username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="用户账号已被禁用",
        )

    client_ip = _get_client_ip(request)
    ip_hashed = hash_ip(client_ip)
    ip_anonymized = anonymize_ip(client_ip)
    user_agent = request.headers.get("User-Agent", "")[:500]

    login_log = UserLoginLog(
        user_id=user.id,
        ip_address=ip_anonymized,
        ip_address_hashed=ip_hashed,
        user_agent=user_agent,
        login_method="password",
    )
    db.add(login_log)
    await db.commit()

    access_token = create_access_token(data={
        "sub": user.username,
        "user_id": user.id,
        "role": user.role,
    })
    refresh_token = create_refresh_token(data={
        "sub": user.username,
        "user_id": user.id,
        "role": user.role,
    })

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 86400,
    }


@router.post("/logout", response_model=Message)
async def logout(
    request: Request,
    db: DbSession,
    current_user: User = Depends(get_current_user),
):
    """用户登出 — 将当前 token 加入黑名单"""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        payload = decode_token(token)
        if payload:
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti:
                expires_at = datetime.fromtimestamp(exp, UTC) if exp else datetime.now(UTC) + timedelta(days=1)
                blacklist_entry = TokenBlacklist(
                    token_jti=jti,
                    expires_at=expires_at,
                )
                db.add(blacklist_entry)
                await db.commit()

    return {"message": "已成功登出"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """获取当前用户信息"""
    return current_user


@router.post("/refresh", response_model=Token)
async def refresh_token(
    request: Request,
    db: DbSession
):
    """刷新 Token"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少刷新 Token",
        )

    token = auth_header.split(" ")[1]
    payload = decode_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="刷新 Token 无效或已过期",
        )

    jti = payload.get("jti")
    if jti:
        stmt = select(TokenBlacklist).where(TokenBlacklist.token_jti == jti)
        result = await db.execute(stmt)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 已被撤销",
            )

    username = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="刷新 Token 无效",
        )

    stmt = select(User).where(User.username == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )

    access_token = create_access_token(data={
        "sub": username,
        "user_id": user.id,
        "role": user.role,
    })
    refresh_token_new = create_refresh_token(data={
        "sub": username,
        "user_id": user.id,
        "role": user.role,
    })

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_new,
        "token_type": "bearer",
        "expires_in": 86400,
    }


@router.post("/change-password", response_model=Message)
async def change_password(
    db: DbSession,
    password_data: PasswordChange,
    current_user: User = Depends(get_current_user)
):
    """修改自己的密码"""
    if not verify_password(password_data.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码不正确",
        )

    current_user.password_hash = hash_password(password_data.new_password)
    await db.commit()

    return {"message": "密码已成功修改"}
