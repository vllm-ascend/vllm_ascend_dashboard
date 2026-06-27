"""
Log Center Pydantic Schemas
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TimeRange(BaseModel):
    """时间范围过滤"""
    start: Optional[datetime] = None
    end: Optional[datetime] = None


class LogQueryRequest(BaseModel):
    """日志查询请求"""
    sources: Optional[list[str]] = Field(
        default=None,
        description="日志源: claude_cli, failure_analysis, app, scheduler",
    )
    levels: Optional[list[str]] = Field(
        default=None,
        description="级别: debug, info, warning, error",
    )
    time_range: Optional[TimeRange] = None
    search: Optional[str] = Field(
        default=None, description="全文搜索关键词"
    )
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(
        default=50, ge=1, le=200, description="每页条数"
    )


class LogEntryMetadata(BaseModel):
    """日志元数据 — 字段按 source 不同而变化"""
    model_config = ConfigDict(extra="allow")

    # claude_cli
    provider: Optional[str] = None
    model: Optional[str] = None
    duration_seconds: Optional[float] = None
    exit_code: Optional[int] = None
    route: Optional[str] = None

    # failure_analysis
    workflow_name: Optional[str] = None
    job_name: Optional[str] = None
    job_id: Optional[int] = None
    analysis_status: Optional[str] = None

    # app / scheduler
    module: Optional[str] = None
    function_name: Optional[str] = None
    line_number: Optional[int] = None

    # scheduler
    task_name: Optional[str] = None
    status: Optional[str] = None


class LogEntryResponse(BaseModel):
    """统一日志条目响应"""
    id: str
    source: str
    level: str
    timestamp: datetime
    summary: str = ""
    content: str = ""
    metadata: LogEntryMetadata = Field(default_factory=LogEntryMetadata)


class LogQueryResponse(BaseModel):
    """日志查询响应"""
    total: int
    page: int
    page_size: int
    entries: list[LogEntryResponse]


class LogSourceInfo(BaseModel):
    """日志源信息"""
    key: str
    label: str
    count: int
    last_entry: Optional[datetime] = None


class LogSourcesResponse(BaseModel):
    """日志源列表响应"""
    sources: list[LogSourceInfo]
