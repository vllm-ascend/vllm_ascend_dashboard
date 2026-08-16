"""
Log Center Pydantic Schemas
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TimeRange(BaseModel):
    """时间范围过滤"""
    start: datetime | None = None
    end: datetime | None = None


class LogQueryRequest(BaseModel):
    """日志查询请求"""
    sources: list[str] | None = Field(
        default=None,
        description="日志源: claude_cli, failure_analysis, app, scheduler",
    )
    levels: list[str] | None = Field(
        default=None,
        description="级别: debug, info, warning, error",
    )
    time_range: TimeRange | None = None
    search: str | None = Field(
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
    provider: str | None = None
    model: str | None = None
    duration_seconds: float | None = None
    exit_code: int | None = None
    route: str | None = None

    # failure_analysis
    workflow_name: str | None = None
    job_name: str | None = None
    job_id: int | None = None
    analysis_status: str | None = None

    # app / scheduler
    module: str | None = None
    function_name: str | None = None
    line_number: int | None = None

    # scheduler
    task_name: str | None = None
    status: str | None = None


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
    last_entry: datetime | None = None


class LogSourcesResponse(BaseModel):
    """日志源列表响应"""
    sources: list[LogSourceInfo]
