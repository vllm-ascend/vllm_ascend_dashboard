"""
Log Center API Routes — unified log query, source listing, detail.
"""
import logging
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession
from app.schemas.logs import (
    LogEntryResponse,
    LogQueryRequest,
    LogQueryResponse,
    LogSourcesResponse,
)
from app.services.log_service import LogService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/sources", response_model=LogSourcesResponse)
async def list_log_sources(db: DbSession):
    """获取可用日志源列表及各源条目数"""
    service = LogService()
    return await service.get_sources(db)


@router.post("/query", response_model=LogQueryResponse)
async def query_logs(filters: LogQueryRequest, db: DbSession):
    """统一日志查询（分页 + 搜索 + 过滤）"""
    service = LogService()
    return await service.query(filters, db)


@router.get("/{log_id:path}", response_model=LogEntryResponse)
async def get_log_entry(log_id: str, db: DbSession):
    """获取单条日志完整内容

    log_id 格式: {source}:{identifier}
    例如: claude_cli:2026-06-26:143000_anthropic_claude-sonnet
    """
    service = LogService()
    decoded_id = unquote(log_id)
    entry = await service.get_entry(decoded_id, db)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Log entry not found: {decoded_id}",
        )
    return entry
