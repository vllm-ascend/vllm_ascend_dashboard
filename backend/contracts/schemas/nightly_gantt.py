"""
Nightly 用例执行甘特图 Schemas

对应 backend/app/services/nightly_gantt_service.py 返回结构，
为前端 TestObservabilityDashboard 的「执行甘特图」Tab 提供数据契约。
"""
from pydantic import BaseModel, Field


class NightlyGanttItem(BaseModel):
    """甘特图单个用例行"""
    phase: str = Field(..., description="阶段：Multi-node / Double-node / Single-node")
    name: str = Field(..., description="用例展示名（从 job 名称提取）")
    raw_name: str = Field(..., description="原始 job 名称")
    start_bj: str = Field(..., description="开始时间（北京时间 HH:MM:SS）")
    end_bj: str = Field(..., description="结束时间（北京时间 HH:MM:SS）")
    start_ms: int = Field(..., description="开始时间 UTC 毫秒戳（甘特图定位用）")
    end_ms: int = Field(..., description="结束时间 UTC 毫秒戳")
    duration: str = Field(..., description="人类可读耗时，如 1h23m")
    duration_seconds: int = Field(..., description="耗时秒数")
    status: str = Field(..., description="状态：ok / err")
    conclusion: str | None = Field(None, description="GitHub job conclusion")
    job_id: int | None = Field(None, description="GitHub job ID")
    job_url: str | None = Field(None, description="GitHub job 详情页 URL")


class NightlyGanttKpi(BaseModel):
    """甘特图 KPI 概览"""
    total: int
    ok: int
    err: int
    ok_rate: float = Field(..., description="成功率 0-1")
    err_rate: float = Field(..., description="失败率 0-1")
    span_ms: int = Field(..., description="时间跨度毫秒")
    phase_counts: dict[str, int] = Field(..., description="各阶段用例数")


class NightlyGanttRunMeta(BaseModel):
    """workflow run 元信息"""
    status: str | None = None
    conclusion: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: int | None = None
    html_url: str | None = None


class NightlyGanttResponse(BaseModel):
    """甘特图接口响应"""
    run_number: int
    run_id: int
    hardware: str = Field(..., description="硬件：A2 / A3")
    workflow_file: str
    workflow_display: str
    run_meta: NightlyGanttRunMeta
    kpi: NightlyGanttKpi
    rows: list[NightlyGanttItem]
    phases: dict[str, list[NightlyGanttItem]] = Field(
        ..., description="按阶段分组的用例行"
    )
