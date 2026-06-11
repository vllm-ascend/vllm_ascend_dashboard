from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


RESOURCE_METRICS_CONFIG_KEY = "resource_metrics_config"


class NpuMetricPoint(BaseModel):
    collected_at: datetime
    npu_utilization: float = 0
    npu_total: float = 0
    npu_used: float = 0
    npu_available: float = 0
    executing_pods_count: int = 0
    pr_count: int = 0
    top_pods: List[Dict[str, Any]] = Field(default_factory=list)


class ClusterNpuMetrics(BaseModel):
    cluster_id: int
    cluster_name: str
    metrics: List[NpuMetricPoint] = Field(default_factory=list)


class NpuMetricsResponse(BaseModel):
    clusters: List[ClusterNpuMetrics] = Field(default_factory=list)


class ResourceMetricsConfigResponse(BaseModel):
    interval_minutes: int = 1
    retention_days: int = 30


class ResourceMetricsConfigUpdate(BaseModel):
    interval_minutes: Optional[int] = Field(None, ge=1, le=60)
    retention_days: Optional[int] = Field(None, ge=1, le=365)