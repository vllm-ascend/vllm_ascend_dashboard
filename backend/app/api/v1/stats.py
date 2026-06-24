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
    current_user: CurrentAdminUser,
    db: DbSession,
    days: int = Query(30, ge=1, le=90, description="统计天数"),
):
    try:
        now = datetime.now(UTC)
        total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        active_today = (await db.execute(select(func.count(distinct(UserLoginLog.user_id)).where(UserLoginLog.login_time >= day_start)))).scalar() or 0
        active_7d = (await db.execute(select(func.count(distinct(UserLoginLog.user_id)).where(UserLoginLog.login_time >= now - timedelta(days=7))))).scalar() or 0
        active_30d = (await db.execute(select(func.count(distinct(UserLoginLog.user_id)).where(UserLoginLog.login_time >= now - timedelta(days=30))))).scalar() or 0

        login_trend = []
        stmt = select(func.date(UserLoginLog.login_time).label("day"), func.count(UserLoginLog.id).label("cnt")).where(UserLoginLog.login_time >= now - timedelta(days=min(days, 30))).group_by(func.date(UserLoginLog.login_time)).order_by(func.date(UserLoginLog.login_time))
        trend_rows = (await db.execute(stmt)).all()
        trend_map = {str(r.day): r.cnt for r in trend_rows}
        for i in range(min(days, 30) - 1, -1, -1):
            ds = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            login_trend.append({"date": ds.strftime("%Y-%m-%d"), "count": trend_map.get(ds.strftime("%Y-%m-%d"), 0)})

        stmt = select(UserLoginLog.user_id, User.username, func.count(UserLoginLog.id).label("cnt")).join(User).where(UserLoginLog.login_time >= now - timedelta(days=days)).group_by(UserLoginLog.user_id, User.username).order_by(func.count(UserLoginLog.id).desc()).limit(10)
        top_users = [{"user_id": r.user_id, "username": r.username, "login_count": r.cnt} for r in (await db.execute(stmt)).all()]

        return LoginStatsResponse(total_users=total_users, active_users_today=active_today, active_users_7days=active_7d, active_users_30days=active_30d, login_trend=login_trend, top_users_by_login_count=top_users)
    except Exception as e:
        logger.error(f"Login stats error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feature-usage", response_model=FeatureUsageStatsResponse, summary="功能使用统计")
async def get_feature_usage_stats(
    current_user: CurrentAdminUser,
    db: DbSession,
    days: int = Query(30, ge=1, le=90, description="统计天数"),
):
    try:
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=days)
        total_requests = (await db.execute(select(func.count(FeatureUsageLog.id)).where(FeatureUsageLog.access_time >= cutoff))).scalar() or 0

        stmt = select(FeatureUsageLog.feature_name, func.count(FeatureUsageLog.id).label("cnt")).where(FeatureUsageLog.access_time >= cutoff).group_by(FeatureUsageLog.feature_name).order_by(func.count(FeatureUsageLog.id).desc()).limit(20)
        feature_ranking = [{"feature_name": r.feature_name, "count": r.cnt} for r in (await db.execute(stmt)).all()]

        stmt = select(FeatureUsageLog.user_id, User.username, func.count(FeatureUsageLog.id).label("cnt")).join(User).where(FeatureUsageLog.access_time >= cutoff).group_by(FeatureUsageLog.user_id, User.username).order_by(func.count(FeatureUsageLog.id).desc()).limit(20)
        user_ranking = [{"user_id": r.user_id, "username": r.username, "count": r.cnt} for r in (await db.execute(stmt)).all()]

        daily_trend = []
        stmt = select(func.date(FeatureUsageLog.access_time).label("day"), func.count(FeatureUsageLog.id).label("cnt")).where(FeatureUsageLog.access_time >= now - timedelta(days=min(days, 30))).group_by(func.date(FeatureUsageLog.access_time)).order_by(func.date(FeatureUsageLog.access_time))
        trend_rows = (await db.execute(stmt)).all()
        trend_map = {str(r.day): r.cnt for r in trend_rows}
        for i in range(min(days, 30) - 1, -1, -1):
            ds = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            daily_trend.append(FeatureUsageTrendPoint(date=ds.strftime("%Y-%m-%d"), count=trend_map.get(ds.strftime("%Y-%m-%d"), 0)))

        return FeatureUsageStatsResponse(total_requests=total_requests, feature_ranking=feature_ranking, user_activity_ranking=user_ranking, daily_trend=daily_trend)
    except Exception as e:
        logger.error(f"Feature usage stats error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
