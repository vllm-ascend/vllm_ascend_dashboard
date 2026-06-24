"""
使用追踪中间件

自动记录所有认证 API 请求到 feature_usage_logs 表。
排除公共路径（/health, /docs, /auth/login, /auth/register, /redoc 等）。
"""
import json
import logging
from datetime import UTC, datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import decode_token
from app.db.base import SessionLocal
from app.models import FeatureUsageLog

logger = logging.getLogger(__name__)

EXCLUDED_PATHS = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
)

FEATURE_NAME_MAP = {
    "/api/v1/ci": "CI看板",
    "/api/v1/models": "模型看板",
    "/api/v1/performance": "性能数据",
    "/api/v1/workflows": "Workflow配置",
    "/api/v1/model-sync-configs": "模型同步配置",
    "/api/v1/auth/me": "用户信息",
    "/api/v1/auth/change-password": "修改密码",
    "/api/v1/users": "用户管理",
    "/api/v1/project-dashboard": "项目看板",
    "/api/v1/resource-dashboard": "资源看板",
    "/api/v1/job-owners": "Job责任人",
    "/api/v1/issue-diagnosis": "问题定位",
    "/api/v1/alert": "告警规则",
    "/api/v1/pr-pipeline": "PR流水线",
    "/api/v1/commit-analysis": "Commit分析",
    "/api/v1/daily-summary": "每日总结",
    "/api/v1/stats": "统计信息",
}


def _extract_feature_name(path: str) -> str:
    for prefix, name in FEATURE_NAME_MAP.items():
        if path.startswith(prefix):
            return name
    return path


class UsageTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        path = request.url.path
        if any(path.startswith(excluded) for excluded in EXCLUDED_PATHS):
            return response

        if request.method not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            return response

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return response

        token = auth_header.split(" ")[1]
        payload = decode_token(token)
        if not payload:
            return response

        user_id = payload.get("user_id")
        if not user_id:
            username = payload.get("sub")
            if username:
                try:
                    from sqlalchemy import select
                    from app.models import User
                    async with SessionLocal() as db:
                        stmt = select(User.id).where(User.username == username)
                        result = await db.execute(stmt)
                        row = result.scalar_one_or_none()
                        if row:
                            user_id = row
                except Exception:
                    pass

        if not user_id:
            return response

        feature_name = _extract_feature_name(path)

        try:
            async with SessionLocal() as db:
                log_entry = FeatureUsageLog(
                    user_id=user_id,
                    feature_name=feature_name,
                    request_path=path,
                    metadata_json={"method": request.method, "status_code": response.status_code},
                )
                db.add(log_entry)
                await db.commit()
        except Exception as e:
            logger.warning(f"Failed to log feature usage: {e}")

        return response
