"""告警规则相关 Pydantic Schemas（条件组模型）"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

VALID_METRIC_FIELDS = [
    "npu_utilization", "npu_total", "npu_used", "npu_available",
    "executing_pods_count", "pr_count",
    "cpu_utilization", "memory_utilization",
    "cpu_cores_used", "cpu_cores_total",
    "memory_bytes_used", "memory_bytes_total",
]

VALID_OPERATORS = [">", "<", ">=", "<=", "=="]

METRIC_FIELD_LABELS = {
    "npu_utilization": "NPU 利用率 (%)",
    "npu_total": "NPU 总量 (卡)",
    "npu_used": "NPU 已用 (卡)",
    "npu_available": "NPU 可用 (卡)",
    "executing_pods_count": "执行中 Pod 数",
    "pr_count": "活跃 PR 数",
    "cpu_utilization": "CPU 利用率 (%)",
    "memory_utilization": "内存利用率 (%)",
    "cpu_cores_used": "CPU 已用 (核)",
    "cpu_cores_total": "CPU 总量 (核)",
    "memory_bytes_used": "内存已用 (GiB)",
    "memory_bytes_total": "内存总量 (GiB)",
}


# ── Condition ──

class AlertConditionCreate(BaseModel):
    metric_field: str
    operator: str
    threshold: float
    is_exclude: bool = False


class AlertConditionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    group_id: int
    metric_field: str
    operator: str
    threshold: float
    is_exclude: bool = False
    display_order: int = 0


# ── Condition Group ──

class AlertConditionGroupCreate(BaseModel):
    logic: str = "AND"
    conditions: list[AlertConditionCreate] = Field(default_factory=list)


class AlertConditionGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: int
    logic: str = "AND"
    display_order: int = 0
    conditions: list[AlertConditionResponse] = Field(default_factory=list)


# ── Rule ──

class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    cluster_id: int | None = None
    node_name: str | None = Field(None, max_length=250)
    enabled: bool = True
    notify_email: bool = True
    notification_email: str | None = Field(None, max_length=100)
    groups: list[AlertConditionGroupCreate] = Field(default_factory=list, min_length=1)


class AlertRuleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    cluster_id: int | None = None
    node_name: str | None = Field(None, max_length=250)
    enabled: bool | None = None
    notify_email: bool | None = None
    notification_email: str | None = Field(None, max_length=100)
    groups: list[AlertConditionGroupCreate] | None = None


class AlertRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    name: str
    cluster_id: int | None = None
    node_name: str | None = None
    enabled: bool
    notify_email: bool
    notification_email: str | None = None
    last_triggered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    groups: list[AlertConditionGroupResponse] = Field(default_factory=list)


# ── History ──

class AlertHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: int
    rule_name: str
    actual_value: float
    cluster_id: int | None = None
    cluster_name: str | None = None
    node_name: str | None = None
    condition_details: dict | None = None
    triggered_at: datetime
    notification_sent: bool
    notification_error: str | None = None
