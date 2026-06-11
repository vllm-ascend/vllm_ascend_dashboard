"""
Pydantic Schemas 定义
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.core.config import settings

# 导出所有 Schema 类
__all__ = [
    # User
    "UserBase", "UserCreate", "UserUpdate", "UserResponse", "PasswordChange", "PasswordReset",
    # Auth
    "Token", "LoginRequest",
    # CI
    "CIResultBase", "CIResultResponse", "CIStats",
    # Model
    "ModelConfigBase", "ModelConfigCreate", "ModelConfigUpdate", "ModelConfigResponse",
    "ModelReportResponse", "ModelReportCreate", "ModelReportUpdate",
    "ModelTrendData", "ModelComparisonRequest", "ModelComparisonResponse",
    "StartupCommandRequest", "StartupCommandResponse",
    # Model Sync Config
    "ModelSyncConfigBase", "ModelSyncConfigCreate", "ModelSyncConfigUpdate", "ModelSyncConfigResponse",
    # Performance
    "PerformanceDataBase", "PerformanceDataCreate", "PerformanceDataResponse", "PerformanceComparison",
    # Job Owner
    "JobOwnerBase", "JobOwnerCreate", "JobOwnerUpdate", "JobOwnerResponse",
    # Project Dashboard
    "ProjectDashboardConfigResponse", "ProjectDashboardConfigUpdate",
    "ReleaseInfo", "VllmVersionInfo", "ModelSupportMatrix", "ModelSupportEntry",
    # Resource Dashboard
    "KubernetesClusterCreate", "KubernetesClusterUpdate", "KubernetesClusterResponse",
    "KubernetesClusterTestResponse", "ResourceQuantity", "ClusterResourceSummary",
    "ResourcePodInfo", "ResourceDashboardResponse",
    "StaleIssue", "PRActionRequest", "TagComparisonRequest", "TagComparisonResult", "CommitInfo",
    # Resource Metrics
    "NpuMetricPoint", "ClusterNpuMetrics", "NpuMetricsResponse",
    "ResourceMetricsConfigResponse", "ResourceMetricsConfigUpdate", "RESOURCE_METRICS_CONFIG_KEY",
    # Daily Summary
    "GenerateSummaryRequest", "FetchDataRequest", "DailySummaryResponse", "DailySummaryListResponse",
    "DailySummaryListItem", "FetchDataResponse", "GenerateSummaryResponse",
    "LLMProviderResponse", "DailySummaryConfigResponse",
    # Common
    "Message", "PaginatedResponse",
]


# ============ User Schemas ============

class UserBase(BaseModel):
    """用户基础 Schema"""
    username: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    email: str | None = Field(None, max_length=100)

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str | None) -> str | None:
        """验证邮箱格式"""
        # 空字符串视为 None
        if v == '':
            return None
        if v is not None and '@' not in v:
            raise ValueError('无效的邮箱格式')
        return v


class UserCreate(UserBase):
    """创建用户 Schema"""
    password: str = Field(..., min_length=6, max_length=128)
    role: str | None = Field(None, description="用户角色 (user, admin, super_admin)")

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        """验证密码强度"""
        if len(v) < 6:
            raise ValueError('密码长度至少为 6 位')
        return v


class UserUpdate(BaseModel):
    """更新用户 Schema"""
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    """用户修改密码 Schema"""
    old_password: str = Field(..., min_length=6, description="当前密码")
    new_password: str = Field(..., min_length=6, description="新密码")

    @field_validator('new_password')
    @classmethod
    def validate_new_password(cls, v: str, info) -> str:
        """验证新密码"""
        if len(v) < 6:
            raise ValueError('新密码长度至少为 6 位')
        # 获取旧密码进行比较
        old_password = info.data.get('old_password')
        if old_password and v == old_password:
            raise ValueError('新密码不能与旧密码相同')
        return v


class PasswordReset(BaseModel):
    """管理员重置用户密码 Schema"""
    new_password: str = Field(..., min_length=6, description="新密码")


class UserResponse(UserBase):
    """用户响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    is_active: bool
    created_at: datetime


# ============ Auth Schemas ============

class Token(BaseModel):
    """Token 响应"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str


# ============ CI Schemas ============

class CIResultBase(BaseModel):
    """CI 结果基础 Schema"""
    workflow_name: str
    run_id: int
    run_number: int | None = None
    job_name: str | None = None
    status: str
    conclusion: str | None = None
    event: str | None = None
    branch: str | None = None
    head_sha: str | None = None
    hardware: str | None = None


class CIResultResponse(CIResultBase):
    """CI 结果响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: int | None = None
    created_at: datetime

    @computed_field
    @property
    def github_html_url(self) -> str | None:
        """构造 GitHub HTML URL"""
        if not self.run_id or not settings.GITHUB_OWNER or not settings.GITHUB_REPO:
            return None
        return f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/runs/{self.run_id}"


class CIJobBase(BaseModel):
    """CI Job 基础 Schema"""
    job_id: int
    run_id: int
    workflow_name: str
    job_name: str
    status: str
    conclusion: str | None = None
    hardware: str | None = None
    runner_name: str | None = None


class CIJobResponse(CIJobBase):
    """CI Job 响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: int | None = None
    runner_labels: list[str] | None = None
    steps_summary: list[dict] | None = None
    created_at: datetime

    @computed_field
    @property
    def github_job_url(self) -> str:
        """构造 GitHub Job URL"""
        if not self.run_id or not self.job_id:
            return ""
        return f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/runs/{self.run_id}/job/{self.job_id}"


class CIJobDetailResponse(CIJobResponse):
    """CI Job 详细响应 Schema"""
    steps_data: list[dict] | None = None
    logs_url: str | None = None


class CIStats(BaseModel):
    """CI 统计信息"""
    total_runs: int
    success_rate: float
    avg_duration_seconds: float | None = None
    last_7_days: dict | None = None


class WorkflowLatestResult(BaseModel):
    """Workflow 最新运行结果"""
    workflow_name: str
    hardware: str | None = None
    latest_run: dict | None = None


class CITrend(BaseModel):
    """CI 趋势数据点"""
    date: str
    total_runs: int
    success_runs: int
    success_rate: float
    avg_duration_seconds: float | None = None


class CISyncResponse(BaseModel):
    """CI 同步响应"""
    success: bool
    message: str
    collected_count: int | None = None


class CIDailyReport(BaseModel):
    """CI 每日报告"""
    date: str
    summary: dict
    workflow_results: list[dict]
    job_stats: list[dict] | None = None
    markdown_report: str


# ============ Model Schemas ============

class ModelConfigBase(BaseModel):
    """模型配置基础 Schema"""
    model_name: str = Field(..., max_length=200)
    series: str | None = None
    config_yaml: str | None = None
    official_doc_url: str | None = Field(None, max_length=500)


class ModelConfigCreate(ModelConfigBase):
    """创建模型配置 Schema"""
    pass


class ModelConfigUpdate(BaseModel):
    """更新模型配置 Schema"""
    series: str | None = None
    config_yaml: str | None = None
    status: str | None = None
    key_metrics_config: dict[str, Any] | None = None
    pass_threshold: dict[str, Any] | None = None
    startup_commands: dict[str, dict[str, dict[str, str]]] | None = None
    official_doc_url: str | None = Field(None, max_length=500)


class ModelConfigResponse(ModelConfigBase):
    """模型配置响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    key_metrics_config: dict[str, Any] | None = None
    pass_threshold: dict[str, Any] | None = None
    startup_commands: dict[str, dict[str, dict[str, str]]] | None = None
    official_doc_url: str | None = None
    created_at: datetime
    updated_at: datetime


class ModelReportBase(BaseModel):
    """模型报告基础 Schema"""
    model_config_id: int
    workflow_run_id: int | None = None
    report_json: dict[str, Any]
    pass_fail: str | None = None
    metrics_json: dict[str, Any] | None = None


class ModelReportCreate(ModelReportBase):
    """创建模型报告 Schema"""
    report_markdown: str | None = None
    auto_pass_fail: str | None = None
    vllm_version: str | None = None
    hardware: str | None = None


class ModelReportUpdate(BaseModel):
    """更新模型报告 Schema"""
    pass_fail: str | None = None
    auto_pass_fail: str | None = None
    manual_override: bool | None = None
    metrics_json: dict[str, Any] | None = None
    vllm_version: str | None = None
    vllm_ascend_version: str | None = None
    hardware: str | None = None
    report_json: dict[str, Any] | None = None
    
    # 新模板字段
    dtype: str | None = None
    features: list[str] | None = None
    serve_cmd: dict[str, Any] | None = None
    environment: dict[str, Any] | None = None
    tasks: list[dict[str, Any]] | None = None


class ModelReportResponse(BaseModel):
    """模型报告响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    model_config_id: int
    workflow_run_id: int | None = None
    report_json: dict[str, Any] | None = None
    report_markdown: str | None = None
    pass_fail: str | None = None
    auto_pass_fail: str | None = None
    manual_override: bool = False
    metrics_json: dict[str, Any] | None = None
    vllm_version: str | None = None
    hardware: str | None = None
    created_at: datetime

    # 新模板字段
    dtype: str | None = None
    features: list[str] | None = None
    serve_cmd: dict[str, Any] | None = None
    environment: dict[str, Any] | None = None
    tasks: list[dict[str, Any]] | None = None


class ModelTrendData(BaseModel):
    """模型趋势数据"""
    date: str
    pass_fail: str | None = None
    metrics: dict[str, Any] = {}
    tasks: list[dict[str, Any]] = []  # Task 数据


class ModelComparisonRequest(BaseModel):
    """模型对比请求"""
    report_ids: list[int] = Field(..., min_length=2, max_length=2, description="需要对比的两个报告 ID")


class ModelComparisonResponse(BaseModel):
    """模型对比响应"""
    reports: list[ModelReportResponse]
    metrics_comparison: dict[str, Any]
    changes: dict[str, Any]
    tasks_comparison: list[dict[str, Any]] | None = None  # Task 级别对比数据


class StartupCommandRequest(BaseModel):
    """启动命令请求"""
    vllm_version: str
    command: str
    notes: str | None = None


class StartupCommandResponse(BaseModel):
    """启动命令响应"""
    vllm_version: str
    command: str
    notes: str | None = None


# ============ Performance Schemas ============

class PerformanceDataBase(BaseModel):
    """性能数据基础 Schema"""
    test_name: str
    hardware: str
    model_name: str
    vllm_version: str | None = None
    test_type: str | None = None


class PerformanceDataCreate(PerformanceDataBase):
    """创建性能数据 Schema"""
    metrics_json: dict
    timestamp: datetime


class PerformanceDataResponse(PerformanceDataBase):
    """性能数据响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    vllm_commit: str | None = None
    vllm_ascend_commit: str | None = None
    metrics_json: dict
    timestamp: datetime
    created_at: datetime


class PerformanceComparison(BaseModel):
    """性能对比结果"""
    baseline: dict
    current: dict
    change: dict


# ============ Workflow Config Schemas ============

class WorkflowConfigBase(BaseModel):
    """Workflow 配置基础 Schema"""
    workflow_name: str = Field(..., description="显示名称，如 'Nightly-A2'")
    workflow_file: str = Field(..., description="workflow 文件名，如 'schedule_nightly_test_a2.yaml'")
    hardware: str = Field(..., description="硬件类型：A2, A3, 310P 等")
    description: str | None = None
    enabled: bool = True
    display_order: int = 0
    last_sync_at: datetime | None = Field(None, description="上次同步时间")


class WorkflowConfigCreate(WorkflowConfigBase):
    """创建 Workflow 配置 Schema"""
    pass


class WorkflowConfigUpdate(BaseModel):
    """更新 Workflow 配置 Schema"""
    workflow_name: str | None = None
    workflow_file: str | None = None
    hardware: str | None = None
    description: str | None = None
    enabled: bool | None = None
    display_order: int | None = None


class WorkflowConfigResponse(WorkflowConfigBase):
    """Workflow 配置响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ============ Model Sync Config Schemas ============

class ModelSyncConfigBase(BaseModel):
    """模型同步配置基础 Schema"""
    workflow_name: str = Field(..., description="workflow 显示名称")
    workflow_file: str = Field(..., description="workflow 文件名")
    artifacts_pattern: str | None = Field(None, description="artifacts 名称匹配规则")
    file_patterns: list[str] | None = Field(None, description="需要下载的文件路径模式")
    branch: str = "main"  # 分支名称过滤（如 "main", "zxy_fix_ci"）
    enabled: bool = True


class ModelSyncConfigCreate(ModelSyncConfigBase):
    """创建模型同步配置 Schema"""
    pass


class ModelSyncConfigUpdate(BaseModel):
    """更新模型同步配置 Schema"""
    workflow_name: str | None = None
    workflow_file: str | None = None
    artifacts_pattern: str | None = None
    file_patterns: list[str] | None = None
    branch: str | None = None
    enabled: bool | None = None


class ModelSyncConfigResponse(ModelSyncConfigBase):
    """模型同步配置响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    last_sync_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Validator 自动解析数据库中的 JSON 字符串
    @field_validator('file_patterns', mode='before')
    @classmethod
    def parse_file_patterns(cls, v):
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, TypeError):
                return None
        return v


# ============ Common Schemas ============

class Message(BaseModel):
    """通用消息响应"""
    message: str


class PaginatedResponse(BaseModel):
    """分页响应"""
    total: int
    items: list[Any]
    page: int
    page_size: int


# ============ Job Owner Schemas ============

class JobOwnerBase(BaseModel):
    """Job 责任人基础 Schema"""
    workflow_name: str = Field(..., description="Workflow 名称")
    job_name: str = Field(..., description="Job 名称")
    display_name: str | None = Field(None, description="Job 显示名")
    owner: str = Field(..., description="责任人姓名")
    email: str | None = Field(None, description="责任人邮箱")
    notes: str | None = Field(None, description="备注信息")
    is_hidden: bool = Field(False, description="是否隐藏")


class JobOwnerCreate(JobOwnerBase):
    """创建 Job 责任人 Schema"""
    pass


class JobOwnerUpdate(BaseModel):
    """更新 Job 责任人 Schema"""
    owner: str | None = None
    email: str | None = None
    notes: str | None = None
    display_name: str | None = None
    is_hidden: bool | None = None


class JobOwnerResponse(JobOwnerBase):
    """Job 责任人响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# ============ Job Stats Schemas ============

class JobStats(BaseModel):
    """Job 统计数据"""
    workflow_name: str
    job_name: str
    display_name: str | None = None
    owner: str | None = None
    owner_email: str | None = None
    total_runs: int
    success_runs: int
    failure_runs: int
    success_rate: float
    avg_duration_seconds: float | None = None
    min_duration_seconds: int | None = None
    max_duration_seconds: int | None = None
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_conclusion: str | None = None


# ============ Project Dashboard Schemas ============

class ReleaseInfo(BaseModel):
    """发布版本信息"""
    version: str
    is_stable: bool
    published_at: datetime
    docker_commands: Dict[str, str]  # mirror name -> docker pull command


class VllmVersionInfo(BaseModel):
    """main 分支 vllm 版本信息"""
    vllm_version: str
    vllm_ascend_version: str
    conf_py_url: str
    updated_at: datetime


class ModelSupportEntry(BaseModel):
    """模型支持矩阵条目"""
    model_name: str
    series: str  # Qwen, Llama, etc.
    support: str  # supported, experimental, not_supported, untested
    note: str | None = None
    doc_link: str | None = None
    # Feature support flags
    weight_format: str | None = None  # e.g., "Bfloat16/W8A8"
    kv_cache_type: str | None = None  # e.g., "Bfloat16/Float16"
    supported_hardware: str | None = None
    chunked_prefill: bool | None = None
    automatic_prefix_cache: bool | None = None
    lora: bool | None = None
    speculative_decoding: bool | None = None
    async_scheduling: bool | None = None
    tensor_parallel: bool | None = None
    pipeline_parallel: bool | None = None
    expert_parallel: bool | None = None
    data_parallel: bool | None = None
    prefilled_decode_disaggregation: bool | None = None
    piecewise_aclgraph: bool | None = None
    fullgraph_aclgraph: bool | None = None
    max_model_len: str | int | None = None
    mlp_weight_prefetch: bool | None = None


class ModelSupportMatrix(BaseModel):
    """模型支持矩阵"""
    entries: List[ModelSupportEntry]
    source_url: str
    updated_at: datetime


class StaleIssue(BaseModel):
    """超期未 review 的 issue"""
    number: int
    title: str
    html_url: str
    created_at: datetime
    updated_at: datetime
    days_stale: int
    author: str | None = None
    labels: List[str] = []


class PRActionRequest(BaseModel):
    """PR 操作请求"""
    pr_number: int
    workflow_id: int | None = None  # 用于重新触发 CI 时指定 workflow


class TagComparisonRequest(BaseModel):
    """Tag 对比请求"""
    base_tag: str
    head_tag: str


class CommitInfo(BaseModel):
    """commit 信息"""
    sha: str
    title: str
    message: str
    author: str
    date: datetime
    category: str  # BugFix, Feature, Performance, Refactor, Doc, CI, Misc
    pr_number: int | None = None


class TagComparisonResult(BaseModel):
    """Tag 对比结果"""
    base_tag: str
    head_tag: str
    total_commits: int
    commits: List[CommitInfo]
    summary: Dict[str, int]  # category -> count
    bug_fixes: List[CommitInfo]
    features: List[CommitInfo]
    performance_improvements: List[CommitInfo]


class ProjectDashboardConfigBase(BaseModel):
    """项目看板配置基础 Schema"""
    config_key: str = Field(..., max_length=100)
    config_value: Dict[str, Any]
    description: str | None = Field(None, max_length=500)


class ProjectDashboardConfigUpdate(BaseModel):
    """更新项目看板配置 Schema"""
    config_value: Dict[str, Any]
    description: str | None = Field(None, max_length=500)


class ProjectDashboardConfigResponse(ProjectDashboardConfigBase):
    """项目看板配置响应 Schema"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


# Import Daily Summary schemas
from .daily_summary import (
    GenerateSummaryRequest, FetchDataRequest, DailySummaryResponse,
    DailySummaryListResponse, DailySummaryListItem, FetchDataResponse,
    GenerateSummaryResponse, LLMProviderResponse, DailySummaryConfigResponse
)

from .resource_dashboard import (
    ClusterResourceSummary,
    KubernetesClusterCreate,
    KubernetesClusterResponse,
    KubernetesClusterTestResponse,
    KubernetesClusterUpdate,
    ResourceDashboardResponse,
    ResourceNodeInfo,
    ResourcePodInfo,
    ResourceQuantity,
)

from .resource_metrics import (
    NpuMetricPoint,
    ClusterNpuMetrics,
    NpuMetricsResponse,
    ResourceMetricsConfigResponse,
    ResourceMetricsConfigUpdate,
    RESOURCE_METRICS_CONFIG_KEY,
)
