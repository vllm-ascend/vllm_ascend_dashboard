from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class KubernetesClusterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    context: str | None = Field(None, max_length=200)
    default_label_selector: str | None = Field(None, max_length=500)
    npu_resource_name: str = Field("huawei.com/Ascend910", min_length=1, max_length=200)
    enabled: bool = True
    display_order: int = 0

    @field_validator("default_label_selector", "context")
    @classmethod
    def normalize_empty_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class KubernetesClusterCreate(KubernetesClusterBase):
    kubeconfig: str = Field(..., min_length=1)


class KubernetesClusterUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    kubeconfig: str | None = None
    context: str | None = Field(None, max_length=200)
    default_label_selector: str | None = Field(None, max_length=500)
    npu_resource_name: str | None = Field(None, min_length=1, max_length=200)
    enabled: bool | None = None
    display_order: int | None = None

    @field_validator("kubeconfig", "default_label_selector", "context")
    @classmethod
    def normalize_empty_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class KubernetesClusterResponse(KubernetesClusterBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kubeconfig_configured: bool = True
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class KubernetesClusterTestResponse(BaseModel):
    success: bool
    message: str
    node_count: int = 0
    pod_count: int = 0


class ResourceQuantity(BaseModel):
    cpu_cores: float = 0
    memory_bytes: int = 0
    npu: float = 0


class ClusterResourceSummary(BaseModel):
    cluster_id: int
    cluster_name: str
    total: ResourceQuantity
    used: ResourceQuantity
    available: ResourceQuantity
    running_instances: int = 0
    executing_pods_count: int = 0
    executed_pods_count: int = 0
    scope: dict[str, Any]
    error: str | None = None


class ResourcePodInfo(BaseModel):
    cluster_id: int
    cluster_name: str
    namespace: str
    name: str
    phase: str | None = None
    status: str | None = None
    node_name: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: int | None = None
    requests: ResourceQuantity
    containers: list[str] = Field(default_factory=list)


class ResourceDashboardResponse(BaseModel):
    generated_at: datetime
    overall: ClusterResourceSummary
    clusters: list[ClusterResourceSummary]
    executing_pods: list[ResourcePodInfo]
    executed_pods: list[ResourcePodInfo]
