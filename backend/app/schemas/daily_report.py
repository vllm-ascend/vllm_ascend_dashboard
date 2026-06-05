"""
每日运行报告 Pydantic Schemas
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DailyReportConfigResponse(BaseModel):
    """报告配置响应"""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_use_tls: bool = True
    report_from_email: str = ""
    report_recipients: str = ""
    report_cc_recipients: str = ""
    report_subject_template: str = "vLLM Ascend 运行报告 - {date}"
    report_enabled: bool = True
    report_schedule_hour: int = 8
    report_schedule_minute: int = 30


class DailyReportConfigUpdate(BaseModel):
    """更新报告配置"""
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = Field(None, ge=1, le=65535)
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: Optional[bool] = None
    report_from_email: Optional[str] = None
    report_recipients: Optional[str] = None
    report_cc_recipients: Optional[str] = None
    report_subject_template: Optional[str] = None
    report_enabled: Optional[bool] = None
    report_schedule_hour: Optional[int] = Field(None, ge=0, le=23)
    report_schedule_minute: Optional[int] = Field(None, ge=0, le=59)


class CISummaryData(BaseModel):
    """CI 概况数据"""
    total_runs: int = 0
    success_runs: int = 0
    failure_runs: int = 0
    success_rate: float = 0.0
    avg_duration_seconds: float | None = None
    failed_workflows: List[Dict[str, Any]] = []


class ModelSummaryData(BaseModel):
    """模型验证概况数据"""
    total_reports: int = 0
    pass_count: int = 0
    fail_count: int = 0
    pass_rate: float = 0.0
    new_models: List[str] = []
    failed_models: List[Dict[str, Any]] = []


class GitHubSummaryData(BaseModel):
    """GitHub 活动概况数据"""
    pr_count: int = 0
    issue_count: int = 0
    commit_count: int = 0
    ai_summary_snippet: str | None = None


class PerformanceSummaryData(BaseModel):
    """性能概况数据"""
    avg_throughput: float | None = None
    avg_p50_latency: float | None = None
    avg_p99_latency: float | None = None


class TimeWindowData(BaseModel):
    """时间窗口数据"""
    ci: CISummaryData = CISummaryData()
    model: ModelSummaryData = ModelSummaryData()
    github: GitHubSummaryData = GitHubSummaryData()
    performance: PerformanceSummaryData = PerformanceSummaryData()


class DailyReportData(BaseModel):
    """完整报告数据"""
    report_date: str
    yesterday: TimeWindowData = TimeWindowData()
    last_week: TimeWindowData = TimeWindowData()
    last_month: TimeWindowData = TimeWindowData()


class DailyReportHistoryResponse(BaseModel):
    """报告发送历史响应"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_date: str
    recipients: str
    subject: str
    status: str
    sent_at: datetime | None = None
    error_message: str | None = None
    ci_summary: Dict[str, Any] | None = None
    model_summary: Dict[str, Any] | None = None
    github_summary: Dict[str, Any] | None = None
    performance_summary: Dict[str, Any] | None = None
    created_at: datetime


class DailyReportHistoryListResponse(BaseModel):
    """报告发送历史列表响应"""
    total: int
    items: List[DailyReportHistoryResponse]


class DailyReportTriggerResponse(BaseModel):
    """手动触发报告响应"""
    success: bool
    message: str
    report_date: str | None = None
    report_id: int | None = None