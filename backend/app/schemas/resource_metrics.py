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


class NodeMetricPoint(BaseModel):
    """单台机器单个时间点的指标"""
    collected_at: datetime
    npu_utilization: float = 0
    npu_total: float = 0
    npu_used: float = 0
    npu_available: float = 0
    cpu_utilization: float = 0
    memory_utilization: float = 0
    executing_pods_count: int = 0


class NodeSeries(BaseModel):
    """单台机器的趋势序列"""
    node_name: str
    metrics: List[NodeMetricPoint] = Field(default_factory=list)


class ClusterNodeMetrics(BaseModel):
    """单个集群下的机器指标集合"""
    cluster_id: int
    cluster_name: str
    nodes: List[NodeSeries] = Field(default_factory=list)


class NodeMetricsResponse(BaseModel):
    """机器维度指标查询响应"""
    clusters: List[ClusterNodeMetrics] = Field(default_factory=list)


class ResourceMetricsConfigResponse(BaseModel):
    interval_minutes: int = 1
    retention_days: int = 30


class ResourceMetricsConfigUpdate(BaseModel):
    interval_minutes: Optional[int] = Field(None, ge=1, le=60)
    retention_days: Optional[int] = Field(None, ge=1, le=365)