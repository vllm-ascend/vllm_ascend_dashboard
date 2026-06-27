"""
数据模型定义
"""
from datetime import UTC, datetime, timezone

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.types import JSON

# 导出所有模型类，方便其他地方导入
__all__ = [
    "Base", "User", "ModelConfig", "ModelReport", "CIResult", "CIJob",
    "WorkflowConfig", "PerformanceData", "JobOwner",
    "ModelSyncConfig", "ProjectDashboardConfig", "KubernetesClusterConfig",
    "DailyPR", "DailyIssue", "DailyCommit", "DailySummary", "LLMProviderConfig",
    "DailyReportHistory", "ResourceNpuMetrics", "JobFailureAnalysis",
    "ResourceNodeMetrics",
    "AlertRule", "AlertConditionGroup", "AlertCondition", "AlertHistory",
    "JobFailureAnalysis",
    "PullRequest",
    "UserLoginLog", "FeatureUsageLog", "TokenBlacklist",
    "TestCase", "TestRun", "TestSuiteSnapshot", "FailureAnnotation",
]


# 创建基类
Base = declarative_base()


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), default="user", index=True)  # user, admin, super_admin
    email = Column(String(100), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # 关系
    model_configs = relationship("ModelConfig", back_populates="creator")
    login_logs = relationship("UserLoginLog", back_populates="user", cascade="all, delete-orphan")
    usage_logs = relationship("FeatureUsageLog", back_populates="user", cascade="all, delete-orphan")


class ModelConfig(Base):
    """模型配置表"""
    __tablename__ = "model_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_name = Column(String(200), nullable=False, index=True)
    series = Column(String(50), index=True)  # Qwen, Llama, DeepSeek, Other
    config_yaml = Column(Text)
    status = Column(String(20), default="active")  # active, inactive
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # 新增字段：关键指标配置、Pass 阈值、启动命令（多版本）
    key_metrics_config = Column(Text)  # JSON 格式，配置关键 metrics
    pass_threshold = Column(Text)  # JSON 格式，Pass 判定阈值
    startup_commands = Column(Text)  # JSON 格式，存储多版本 vLLM 启动命令
    official_doc_url = Column(String(500))  # 官方文档链接

    # 关系
    creator = relationship("User", back_populates="model_configs")
    reports = relationship("ModelReport", back_populates="model_config", cascade="all, delete-orphan")


class ModelReport(Base):
    """模型看板报告表"""
    __tablename__ = "model_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_config_id = Column(Integer, ForeignKey("model_configs.id"), index=True)
    workflow_run_id = Column(BigInteger, index=True)  # GitHub workflow run ID
    report_json = Column(JSON, nullable=False)
    pass_fail = Column(String(10))  # pass, fail
    metrics_json = Column(JSON)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), index=True)

    # 新增字段
    report_markdown = Column(Text)  # Markdown 格式报告原文
    auto_pass_fail = Column(String(10))  # 系统自动判定的结果
    manual_override = Column(Boolean, default=False)  # 是否手动覆盖过 Pass/Fail
    vllm_version = Column(String(50))  # vLLM 版本
    hardware = Column(String(20))  # 硬件类型：A2, A3

    # 新模板字段
    dtype = Column(String(50))  # 权重类型：w8a8, fp16 等
    features = Column(JSON)  # 特性列表：["mlp_prefetch", "bbb"]
    serve_cmd = Column(JSON)  # 启动命令：{"mix": "..."} 或 {"pd": {...}}
    environment = Column(JSON)  # 环境变量：{"ENV1": "aaa"}
    tasks = Column(JSON)  # 完整的 tasks 数组（包含 test_input, target 等）

    # 关系
    model_config = relationship("ModelConfig", back_populates="reports")


class CIResult(Base):
    """CI 结果表（workflow 级别）"""
    __tablename__ = "ci_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_name = Column(String(100), nullable=False, index=True)
    run_id = Column(BigInteger, nullable=False, index=True, unique=True)
    run_number = Column(Integer)  # workflow run 编号
    status = Column(String(20), index=True)  # completed, in_progress, queued
    conclusion = Column(String(20))  # success, failure, cancelled
    event = Column(String(50))  # schedule, push, pull_request
    branch = Column(String(100))  # 分支名
    head_sha = Column(String(100))  # commit sha
    started_at = Column(TIMESTAMP, index=True)
    completed_at = Column(TIMESTAMP, index=True)
    duration_seconds = Column(Integer)
    hardware = Column(String(20), index=True)  # A2, A3
    data = Column(Text)  # 完整的 workflow run 数据
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), index=True)
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class CIJob(Base):
    """CI Job 表（job 级别）"""
    __tablename__ = "ci_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(BigInteger, nullable=False, index=True, unique=True)  # GitHub job ID
    run_id = Column(BigInteger, nullable=False, index=True)  # 关联的 workflow run_id
    workflow_name = Column(String(100), nullable=False, index=True)
    job_name = Column(String(500), nullable=False)  # job 名称
    status = Column(String(20), index=True)  # completed, in_progress, queued
    conclusion = Column(String(50))  # success, failure, cancelled, skipped
    started_at = Column(TIMESTAMP, index=True)
    completed_at = Column(TIMESTAMP, index=True)
    duration_seconds = Column(Integer)
    hardware = Column(String(20), index=True)  # A2, A3, 310P
    runner_name = Column(String(200))  # runner 名称
    runner_labels = Column(Text)  # runner 标签（JSON 格式）
    steps_data = Column(Text)  # job steps 详细信息（JSON 格式）
    logs_url = Column(String(500))  # job 日志 URL
    data = Column(Text)  # 完整的 job 数据 (LONGTEXT)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), index=True)
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class WorkflowConfig(Base):
    """Workflow 配置表"""
    __tablename__ = "workflow_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_name = Column(String(100), nullable=False, unique=True, index=True)  # 显示名称，如 "Nightly-A2"
    workflow_file = Column(String(100), nullable=False, unique=True)  # workflow 文件名，如 "schedule_nightly_test_a2.yaml"
    hardware = Column(String(20), nullable=False)  # 硬件类型：A2, A3, 310P 等
    event = Column(String(50), default="schedule")  # 采集的事件类型：schedule/push/pull_request/workflow_dispatch，空=不过滤
    actor = Column(String(100), nullable=True)  # 触发人过滤（GitHub actor login），空=不过滤
    description = Column(String(500))  # 描述信息
    enabled = Column(Boolean, default=True)  # 是否启用
    display_order = Column(Integer, default=0)  # 显示顺序

    # 新增字段：同步状态跟踪（用于前端显示）
    last_sync_at = Column(TIMESTAMP)  # 上次同步时间（包括手动和自动）

    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class PerformanceData(Base):
    """性能数据表"""
    __tablename__ = "performance_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    test_name = Column(String(200), nullable=False, index=True)
    hardware = Column(String(20), nullable=False, index=True)  # A2, A3
    model_name = Column(String(200), nullable=False, index=True)
    vllm_version = Column(String(50), index=True)
    vllm_commit = Column(String(40))
    vllm_ascend_commit = Column(String(40))
    test_type = Column(String(20))  # latency, throughput, serving
    metrics_json = Column(Text, nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False, index=True)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))


class JobOwner(Base):
    """Job 责任人配置表"""
    __tablename__ = "job_owners"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_name = Column(String(100), nullable=False, index=True)  # workflow 名称
    job_name = Column(String(500), nullable=False, index=True)  # job 名称
    display_name = Column(String(200))  # Job 显示名（可选）
    owner = Column(String(100), nullable=False)  # 责任人姓名
    email = Column(String(100))  # 责任人邮箱（可选）
    notes = Column(String(500))  # 备注信息（可选）
    is_hidden = Column(Boolean, default=False, index=True)  # 是否隐藏
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # 唯一约束：workflow_name + job_name 组合唯一
    __table_args__ = (
        UniqueConstraint('workflow_name', 'job_name', name='uq_job_owner_workflow_job'),
    )


class ModelSyncConfig(Base):
    """模型报告同步配置表"""
    __tablename__ = "model_sync_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workflow_name = Column(String(100), nullable=False, index=True)  # workflow 显示名称
    workflow_file = Column(String(100), nullable=False, unique=True)  # workflow 文件名
    artifacts_pattern = Column(String(200))  # artifacts 名称匹配规则（如 "model-report-*"）
    file_patterns = Column(Text)  # JSON 数组，需要下载的文件路径模式（如 ["results/*.yaml", "lm_eval_results/*.json"]）
    branch = Column(String(100), default="main")  # 分支名称过滤（如 "main", "zxy_fix_ci"）
    enabled = Column(Boolean, default=True)  # 是否启用
    last_sync_at = Column(TIMESTAMP)  # 上次同步时间
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class ProjectDashboardConfig(Base):
    """项目看板配置表"""
    __tablename__ = "project_dashboard_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False, index=True)  # 配置键
    config_value = Column(JSON, nullable=False)  # 配置值（JSON 格式）
    description = Column(String(500))  # 配置描述
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class KubernetesClusterConfig(Base):
    """Kubernetes 集群配置表"""
    __tablename__ = "kubernetes_cluster_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(String(500))
    kubeconfig_encrypted = Column(Text, nullable=False)
    context = Column(String(200))
    default_label_selector = Column(String(500))
    namespaces = Column(String(500), nullable=False, default="vllm-project")
    npu_resource_name = Column(String(200), nullable=False, default="huawei.com/Ascend910")
    enabled = Column(Boolean, default=True, index=True)
    display_order = Column(Integer, default=0)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class DailyReportHistory(Base):
    """每日运行报告发送历史表"""
    __tablename__ = "daily_report_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_date = Column(String(10), nullable=False, index=True)
    recipients = Column(Text, nullable=False)
    subject = Column(String(200), nullable=False)
    status = Column(String(20), default="pending", index=True)
    sent_at = Column(TIMESTAMP)
    error_message = Column(Text)
    ci_summary = Column(JSON)
    model_summary = Column(JSON)
    github_summary = Column(JSON)
    performance_summary = Column(JSON)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))


class ResourceNpuMetrics(Base):
    """资源 NPU 指标采集表"""
    __tablename__ = "resource_npu_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cluster_id = Column(Integer, ForeignKey("kubernetes_cluster_configs.id"), nullable=False, index=True)
    cluster_name = Column(String(100), nullable=False)
    npu_total = Column(Float, default=0)
    npu_used = Column(Float, default=0)
    npu_available = Column(Float, default=0)
    npu_utilization = Column(Float, default=0)
    executing_pods_count = Column(Integer, default=0)
    pr_count = Column(Integer, default=0)
    top_pods_json = Column(JSON)
    collected_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), index=True)


class ResourceNodeMetrics(Base):
    """资源节点指标采集表"""
    __tablename__ = "resource_node_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cluster_id = Column(Integer, ForeignKey("kubernetes_cluster_configs.id"), nullable=False, index=True)
    cluster_name = Column(String(100), nullable=False)
    node_name = Column(String(250), nullable=False, index=True)
    cpu_cores_total = Column(Float, default=0)
    cpu_cores_used = Column(Float, default=0)
    cpu_cores_available = Column(Float, default=0)
    cpu_utilization = Column(Float, default=0)
    memory_bytes_total = Column(Float, default=0)
    memory_bytes_used = Column(Float, default=0)
    memory_bytes_available = Column(Float, default=0)
    memory_utilization = Column(Float, default=0)
    npu_total = Column(Float, default=0)
    npu_used = Column(Float, default=0)
    npu_available = Column(Float, default=0)
    npu_utilization = Column(Float, default=0)
    executing_pods_count = Column(Integer, default=0)
    collected_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), index=True)


class AlertRule(Base):
    """告警规则表（规则头）"""
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    cluster_id = Column(Integer, ForeignKey("kubernetes_cluster_configs.id"), nullable=True)
    node_name = Column(String(250), nullable=True)
    enabled = Column(Boolean, default=True, index=True)
    notify_email = Column(Boolean, default=True)
    notification_email = Column(String(100), nullable=True)
    last_triggered_at = Column(TIMESTAMP, nullable=True)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class JobFailureAnalysis(Base):
    """CI Job 失败分析表"""
    __tablename__ = "job_failure_analysis"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(BigInteger, nullable=False, unique=True, index=True)
    run_id = Column(BigInteger, nullable=False, index=True)
    workflow_name = Column(String(100), nullable=False, index=True)
    job_name = Column(String(500), nullable=False)
    failure_date = Column(TIMESTAMP, nullable=False, index=True)

    failure_fingerprint = Column(String(32), index=True)
    reused_analysis_id = Column(Integer)

    problem_category = Column(String(20), index=True)
    root_cause_summary = Column(String(500))
    improvement_measures_summary = Column(String(500))
    report_file_path = Column(String(200))
    pdf_file_path = Column(String(200))

    llm_provider = Column(String(50))
    llm_model = Column(String(100))
    prompt_tokens = Column(Integer)
    completion_tokens = Column(Integer)
    generation_time_seconds = Column(Float)

    analysis_status = Column(String(20), default="pending", index=True)
    error_message = Column(String(500))
    triggered_by = Column(String(20), default="manual")  # "manual" | "scheduler"
    share_token = Column(String(64), unique=True, index=True)  # 公开分享 token
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class AlertConditionGroup(Base):
    """告警条件组表（组间 AND）"""
    __tablename__ = "alert_condition_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id"), nullable=False, index=True)
    logic = Column(String(10), nullable=False, default="AND")
    display_order = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))


class AlertCondition(Base):
    """告警条件表"""
    __tablename__ = "alert_conditions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("alert_condition_groups.id"), nullable=False, index=True)
    metric_field = Column(String(50), nullable=False)
    operator = Column(String(10), nullable=False)
    threshold = Column(Float, nullable=False)
    is_exclude = Column(Boolean, default=False)
    display_order = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))


class AlertHistory(Base):
    """告警触发历史表"""
    __tablename__ = "alert_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id"), nullable=False, index=True)
    rule_name = Column(String(100), nullable=False)
    actual_value = Column(Float, nullable=False)
    cluster_id = Column(Integer, nullable=True)
    cluster_name = Column(String(100), nullable=True)
    node_name = Column(String(250), nullable=True)
    condition_details = Column(JSON, nullable=True)
    triggered_at = Column(TIMESTAMP, nullable=False, default=lambda: datetime.now(UTC), index=True)
    notification_sent = Column(Boolean, default=False)
    notification_error = Column(Text, nullable=True)


class UserLoginLog(Base):
    __tablename__ = "user_login_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    login_time = Column(TIMESTAMP, nullable=False, default=lambda: datetime.now(UTC), index=True)
    ip_address = Column(String(64))
    ip_address_hashed = Column(String(64))
    user_agent = Column(String(500))
    login_method = Column(String(20), default="password")
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))

    user = relationship("User", back_populates="login_logs")


class FeatureUsageLog(Base):
    __tablename__ = "feature_usage_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    feature_name = Column(String(100), nullable=False, index=True)
    request_path = Column(String(500), nullable=False, index=True)
    access_time = Column(TIMESTAMP, nullable=False, default=lambda: datetime.now(UTC), index=True)
    metadata_json = Column(JSON)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))

    user = relationship("User", back_populates="usage_logs")


class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token_jti = Column(String(100), unique=True, nullable=False, index=True)
    blacklisted_at = Column(TIMESTAMP, nullable=False, default=lambda: datetime.now(UTC), index=True)
    expires_at = Column(TIMESTAMP, nullable=False, index=True)


# 导入每日总结相关模型
from .daily_summary import DailyPR, DailyIssue, DailyCommit, DailySummary, LLMProviderConfig

from .test_board import TestCase, TestRun, TestSuiteSnapshot, FailureAnnotation


class PullRequest(Base):
    """PR 全生命周期数据"""
    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pr_number = Column(BigInteger, nullable=False, index=True)
    owner = Column(String(100), nullable=False, index=True)
    repo = Column(String(100), nullable=False, index=True)

    title = Column(String(500), nullable=False)
    author = Column(String(100), nullable=False, index=True)
    author_avatar_url = Column(String(500))
    html_url = Column(String(500))
    state = Column(String(20), nullable=False, index=True)
    is_draft = Column(Boolean, default=False, index=True)
    labels = Column(JSON, default=list)

    head_branch = Column(String(200))
    head_sha = Column(String(40), index=True)
    base_branch = Column(String(200))

    additions = Column(Integer, default=0)
    deletions = Column(Integer, default=0)
    changed_files = Column(Integer, default=0)

    pipeline_stage = Column(String(20), index=True)
    review_status = Column(String(20), index=True)
    reviewers = Column(JSON, default=list)
    ci_status = Column(String(20), index=True)
    ci_workflow_run_id = Column(BigInteger)

    first_review_at = Column(TIMESTAMP)
    first_approved_at = Column(TIMESTAMP)
    ci_started_at = Column(TIMESTAMP)
    ci_completed_at = Column(TIMESTAMP)
    merged_at = Column(TIMESTAMP)
    closed_at = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, nullable=False, index=True, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    data = Column(JSON)

    __table_args__ = (
        UniqueConstraint("pr_number", "owner", "repo", name="uq_pr_owner_repo"),
    )
