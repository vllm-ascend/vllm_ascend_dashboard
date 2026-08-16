"""
用户管理 API 路由
Phase 1: 基础版本，提供用户管理接口
"""
import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from api.deps import CurrentAdminUser, CurrentSuperAdminUser, DbSession
from contracts.schemas import Message, PasswordReset, UserCreate, UserResponse, UserUpdate
from infrastructure.core.security import hash_password
from infrastructure.persistence.models import User

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=list[UserResponse])
async def list_users(
    db: DbSession,
    current_user: CurrentSuperAdminUser
):
    """获取用户列表（仅超级管理员）"""
    # 使用 execution_options 确保每次请求都从数据库获取最新数据
    result = await db.execute(
        select(User).execution_options(populate_existing=True)
    )
    users = result.scalars().all()
    return users


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    db: DbSession,
    user_data: UserCreate,
    current_user: CurrentSuperAdminUser
):
    """创建用户（仅超级管理员）"""
    # 检查用户名是否已存在
    stmt = select(User).where(User.username == user_data.username)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在",
        )

    # 创建用户
    user = User(
        username=user_data.username,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        role=user_data.role or "user",
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    return user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    db: DbSession,
    user_id: int,
    current_user: CurrentAdminUser
):
    """获取用户详情"""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    db: DbSession,
    user_id: int,
    user_data: UserUpdate,
    current_user: CurrentAdminUser
):
    """更新用户信息"""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 普通管理员不能修改超级管理员
    if user.role == "super_admin" and current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="普通管理员不能修改超级管理员用户",
        )

    # 更新字段
    update_data = user_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    return user


@router.delete("/{user_id}", response_model=Message)
async def delete_user(
    db: DbSession,
    user_id: int,
    current_user: CurrentSuperAdminUser
):
    """删除用户（仅超级管理员）"""
    try:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在",
            )

        # 不允许删除自己
        if user.id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="不能删除自己",
            )

        logger.info(f"Deleting user: {user.username} (ID: {user_id}) by {current_user.username}")
        await db.delete(user)
        await db.commit()

        logger.info(f"User {user.username} (ID: {user_id}) deleted successfully")
        return {"message": "用户已成功删除"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}", exc_info=True)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除失败：{str(e)}",
        )


@router.put("/{user_id}/password", response_model=Message)
async def reset_user_password(
    db: DbSession,
    user_id: int,
    password_data: PasswordReset,
    current_user: CurrentAdminUser
):
    """重置用户密码（管理员权限）"""
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    # 不允许重置自己的密码（应使用修改密码接口）
    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请使用修改密码接口修改自己的密码",
        )

    # 更新密码
    user.password_hash = hash_password(password_data.new_password)
    await db.commit()

    return {"message": "用户密码已成功重置"}
