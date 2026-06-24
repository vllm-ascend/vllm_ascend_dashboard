"""
统计信息 API 路由

提供登录统计和功能使用统计接口，仅管理员可见。
"""
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, func, distinct, and_

from app.api.deps import CurrentAdminUser, DbSession
from app.models import User, UserLoginLog, FeatureUsageLog
from app.schemas import LoginStatsResponse, FeatureUsageStatsResponse, FeatureUsageTrendPoint

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/login", response_model=LoginStatsResponse, summary="登录统计")
async def get_login_stats(
    db: DbSession,
    days: int = Query(30, ge=1, le=90, description="统计天数"),
    current_user: CurrentAdminUser,
):
    """获取登录统计信息（管理员权限）"""
    try:
        total_users_result = await db.execute(select(func.count(User.id)))
        total_users = total_users_result.scalar() or 0

        now = datetime.now(UTC)

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(func.count(distinct(UserLoginLog.user_id))).where(
            UserLoginLog.login_time >= today_start
        )
        result = await db.execute(stmt)
        active_today = result.scalar() or 0

        stmt = select(func.count(distinct(UserLoginLog.user_id))).where(
            UserLoginLog.login_time >= now - timedelta(days=7)
        )
        result = await db.execute(stmt)
        active_7d = result.scalar() or 0

        stmt = select(func.count(distinct(UserLoginLog.user_id))).where(
            UserLoginLog.login_time >= now - timedelta(days=30)
        )
        result = await db.execute(stmt)
        active_30d = result.scalar() or 0

        login_trend = []
        for i in range(min(days, 30)):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            stmt = select(func.count(UserLoginLog.id)).where(
                and_(UserLoginLog.login_time >= day_start, UserLoginLog.login_time < day_end)
            )
            result = await db.execute(stmt)
            count = result.scalar() or 0

            login_trend.append({
                "date": day_start.strftime("%Y-%m-%d"),
                "count": count,
            })

        stmt = (
            select(UserLoginLog.user_id, User.username, func.count(UserLoginLog.id).label("login_count"))
            .join(User, UserLoginLog.user_id == User.id)
            .where(UserLoginLog.login_time >= now - timedelta(days=days))
            .group_by(UserLoginLog.user_id, User.username)
            .order_by(func.count(UserLoginLog.id).desc())
            .limit(10)
        )
        result = await db.execute(stmt)
        top_users = [
            {"user_id": row.user_id, "username": row.username, "login_count": row.login_count}
            for row in result.all()
        ]

        login_trend.reverse()

        return LoginStatsResponse(
            total_users=total_users,
            active_users_today=active_today,
            active_users_7days=active_7d,
            active_users_30days=active_30d,
            login_trend=login_trend,
            top_users_by_login_count=top_users,
        )
    except Exception as e:
        logger.error(f"Failed to get login stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feature-usage", response_model=FeatureUsageStatsResponse, summary="功能使用统计")
async def get_feature_usage_stats(
    db: DbSession,
    days: int = Query(30, ge=1, le=90, description="统计天数"),
    current_user: CurrentAdminUser,
):
    """获取功能使用统计信息（管理员权限）"""
    try:
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=days)

        total_result = await db.execute(
            select(func.count(FeatureUsageLog.id)).where(FeatureUsageLog.access_time >= cutoff)
        )
        total_requests = total_result.scalar() or 0

        stmt = (
            select(FeatureUsageLog.feature_name, func.count(FeatureUsageLog.id).label("count"))
            .where(FeatureUsageLog.access_time >= cutoff)
            .group_by(FeatureUsageLog.feature_name)
            .order_by(func.count(FeatureUsageLog.id).desc())
            .limit(20)
        )
        result = await db.execute(stmt)
        feature_ranking = [
            {"feature_name": row.feature_name, "count": row.count}
            for row in result.all()
        ]

        stmt = (
            select(FeatureUsageLog.user_id, User.username, func.count(FeatureUsageLog.id).label("count"))
            .join(User, FeatureUsageLog.user_id == User.id)
            .where(FeatureUsageLog.access_time >= cutoff)
            .group_by(FeatureUsageLog.user_id, User.username)
            .order_by(func.count(FeatureUsageLog.id).desc())
            .limit(20)
        )
        result = await db.execute(stmt)
        user_activity_ranking = [
            {"user_id": row.user_id, "username": row.username, "count": row.count}
            for row in result.all()
        ]

        daily_trend = []
        for i in range(min(days, 30)):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            stmt = select(func.count(FeatureUsageLog.id)).where(
                and_(FeatureUsageLog.access_time >= day_start, FeatureUsageLog.access_time < day_end)
            )
            result = await db.execute(stmt)
            count = result.scalar() or 0

            daily_trend.append(FeatureUsageTrendPoint(
                date=day_start.strftime("%Y-%m-%d"),
                count=count,
            ))

        daily_trend.reverse()

        return FeatureUsageStatsResponse(
            total_requests=total_requests,
            feature_ranking=feature_ranking,
            user_activity_ranking=user_activity_ranking,
            daily_trend=daily_trend,
        )
    except Exception as e:
        logger.error(f"Failed to get feature usage stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
