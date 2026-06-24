import logging
from datetime import UTC, datetime

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import decode_token
from app.db.base import SessionLocal
from app.models import FeatureUsageLog

logger = logging.getLogger(__name__)

EXCLUDED_PATHS = ("/health", "/docs", "/redoc", "/openapi.json", "/auth/login", "/auth/register", "/auth/refresh")

FEATURE_NAME_MAP = {
    "/api/v1/ci": "CI看板", "/api/v1/models": "模型看板", "/api/v1/performance": "性能数据",
    "/api/v1/workflows": "Workflow配置", "/api/v1/model-sync-configs": "模型同步配置",
    "/api/v1/auth/me": "用户信息", "/api/v1/auth/change-password": "修改密码",
    "/api/v1/users": "用户管理", "/api/v1/project-dashboard": "项目看板",
    "/api/v1/resource-dashboard": "资源看板", "/api/v1/job-owners": "Job责任人",
    "/api/v1/issue-diagnosis": "问题定位", "/api/v1/alert": "告警规则",
    "/api/v1/pr-pipeline": "PR流水线", "/api/v1/commit-analysis": "Commit分析",
    "/api/v1/daily-summary": "每日总结", "/api/v1/stats": "统计信息",
}


def _feature_name(path: str) -> str:
    for prefix, name in FEATURE_NAME_MAP.items():
        if path.startswith(prefix):
            return name
    return path


class UsageTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        path = request.url.path
        if any(path.startswith(e) for e in EXCLUDED_PATHS) or request.method == "OPTIONS":
            return response

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return response

        payload = decode_token(auth_header.split(" ")[1])
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
                        user_id = (await db.execute(select(User.id).where(User.username == username))).scalar_one_or_none()
                except Exception:
                    pass
        if not user_id:
            return response

        try:
            async with SessionLocal() as db:
                db.add(FeatureUsageLog(user_id=user_id, feature_name=_feature_name(path), request_path=path, metadata_json={"method": request.method, "status_code": response.status_code}))
                await db.commit()
        except Exception as e:
            logger.warning(f"Failed to log feature usage: {e}")
        return response
