"""
数据模型定义
"""
from datetime import UTC, datetime, timezone

from sqlalchemy import (
    TIMESTAMP,
    BigInteger,
    Boolean,
    Column,
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
    # 每日总结相关模型
    "DailyPR", "DailyIssue", "DailyCommit", "DailySummary", "LLMProviderConfig"
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
    email = Column(String(100))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC))
    updated_at = Column(TIMESTAMP, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # 关系
    model_configs = relationship("ModelConfig", back_populates="creator")


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


# 导入每日总结相关模型
from .daily_summary import DailyPR, DailyIssue, DailyCommit, DailySummary, LLMProviderConfig
