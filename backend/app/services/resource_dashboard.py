from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.models import KubernetesClusterConfig
from app.schemas import (
    ClusterResourceSummary,
    ResourceDashboardResponse,
    ResourceNodeInfo,
    ResourcePodInfo,
    ResourceQuantity,
)
from app.services.kubernetes_client import KubernetesClientFactory, list_nodes, list_pods

EXECUTING_PHASES = {"Pending", "Running", "Unknown"}
EXECUTED_PHASES = {"Succeeded", "Failed"}
RESOURCE_DASHBOARD_NAMESPACE = "vllm-project"


class ResourceDashboardService:
    def __init__(self) -> None:
        self.client_factory = KubernetesClientFactory()

    async def build_dashboard(
        self,
        clusters: list[KubernetesClusterConfig],
        label_selector: str | None = None,
        include_pods: bool = True,
    ) -> ResourceDashboardResponse:
        summaries: list[ClusterResourceSummary] = []
        executing_pods: list[ResourcePodInfo] = []
        executed_pods: list[ResourcePodInfo] = []

        for cluster in clusters:
            try:
                summary, cluster_executing, cluster_executed = await self.build_cluster_summary(
                    cluster,
                    label_selector,
                    include_pods,
                )
            except Exception as exc:
                summary = ClusterResourceSummary(
                    cluster_id=cluster.id,
                    cluster_name=cluster.name,
                    total=ResourceQuantity(),
                    used=ResourceQuantity(),
                    available=ResourceQuantity(),
                    scope={
                        "namespaces": [RESOURCE_DASHBOARD_NAMESPACE],
                        "label_selector": label_selector or cluster.default_label_selector,
                    },
                    error=str(exc),
                )
                cluster_executing = []
                cluster_executed = []

            summaries.append(summary)
            executing_pods.extend(cluster_executing)
            executed_pods.extend(cluster_executed)

        overall = self._build_overall_summary(summaries)
        return ResourceDashboardResponse(
            generated_at=datetime.now(UTC),
            overall=overall,
            clusters=summaries,
            executing_pods=executing_pods,
            executed_pods=executed_pods,
        )

    async def build_cluster_summary(
        self,
        cluster: KubernetesClusterConfig,
        label_selector: str | None,
        include_pods: bool,
    ) -> tuple[ClusterResourceSummary, list[ResourcePodInfo], list[ResourcePodInfo]]:
        resolved_label_selector = label_selector if label_selector is not None else cluster.default_label_selector

        api_client = await self.client_factory.create_api_client(cluster)
        try:
            nodes = await list_nodes(api_client)
            pods = await list_pods(api_client, [RESOURCE_DASHBOARD_NAMESPACE], resolved_label_selector)
        finally:
            await api_client.close()

        total = self._sum_node_allocatable(nodes, cluster.npu_resource_name)
        node_resources = self._build_node_resources(nodes, cluster.npu_resource_name)
        used = ResourceQuantity()
        running_instances = 0
        executing_infos: list[ResourcePodInfo] = []
        executed_infos: list[ResourcePodInfo] = []

        visible_pods = []
        for pod in pods:
            phase = pod.status.phase if pod.status else None
            pod_requests = self._pod_requests(pod, cluster.npu_resource_name)
            if pod_requests.npu <= 0:
                continue
            visible_pods.append(pod)
            node_resource = node_resources.get(getattr(pod.spec, "node_name", None))
            if phase == "Running":
                running_instances += 1
                if node_resource:
                    node_resource.running_instances += 1
            if phase in EXECUTING_PHASES:
                used = self._add_quantity(used, pod_requests)
                if node_resource:
                    node_resource.used = self._add_quantity(node_resource.used, pod_requests)
                    node_resource.executing_pods_count += 1
                if include_pods:
                    executing_infos.append(self._pod_info(cluster, pod, pod_requests))
            elif phase in EXECUTED_PHASES and include_pods:
                executed_infos.append(self._pod_info(cluster, pod, pod_requests))

        summary = ClusterResourceSummary(
            cluster_id=cluster.id,
            cluster_name=cluster.name,
            total=total,
            used=used,
            available=ResourceQuantity(
                cpu_cores=max(total.cpu_cores - used.cpu_cores, 0),
                memory_bytes=max(total.memory_bytes - used.memory_bytes, 0),
                npu=max(total.npu - used.npu, 0),
            ),
            running_instances=running_instances,
            executing_pods_count=len([pod for pod in visible_pods if pod.status and pod.status.phase in EXECUTING_PHASES]),
            executed_pods_count=len([pod for pod in visible_pods if pod.status and pod.status.phase in EXECUTED_PHASES]),
            node_resources=self._finalize_node_resources(node_resources),
            scope={
                "namespaces": [RESOURCE_DASHBOARD_NAMESPACE],
                "label_selector": resolved_label_selector,
            },
        )
        return summary, executing_infos, executed_infos

    async def test_cluster(self, cluster: KubernetesClusterConfig) -> tuple[int, int]:
        api_client = await self.client_factory.create_api_client(cluster)
        try:
            nodes = await list_nodes(api_client)
            pods = await list_pods(api_client, [RESOURCE_DASHBOARD_NAMESPACE], cluster.default_label_selector)
            return len(nodes), len(pods)
        finally:
            await api_client.close()

    def _build_overall_summary(self, summaries: list[ClusterResourceSummary]) -> ClusterResourceSummary:
        total = ResourceQuantity()
        used = ResourceQuantity()
        available = ResourceQuantity()
        running_instances = 0
        executing_count = 0
        executed_count = 0

        for summary in summaries:
            if summary.error:
                continue
            total = self._add_quantity(total, summary.total)
            used = self._add_quantity(used, summary.used)
            available = self._add_quantity(available, summary.available)
            running_instances += summary.running_instances
            executing_count += summary.executing_pods_count
            executed_count += summary.executed_pods_count

        return ClusterResourceSummary(
            cluster_id=0,
            cluster_name="总资源",
            total=total,
            used=used,
            available=available,
            running_instances=running_instances,
            executing_pods_count=executing_count,
            executed_pods_count=executed_count,
            scope={"all_clusters": True},
        )

    def _sum_node_allocatable(self, nodes: list[Any], npu_resource_name: str) -> ResourceQuantity:
        total = ResourceQuantity()
        for node in nodes:
            allocatable = node.status.allocatable or {}
            total.cpu_cores += parse_cpu(allocatable.get("cpu"))
            total.memory_bytes += parse_memory(allocatable.get("memory"))
            total.npu += parse_number(allocatable.get(npu_resource_name))
        return total

    def _build_node_resources(self, nodes: list[Any], npu_resource_name: str) -> dict[str, ResourceNodeInfo]:
        node_resources = {}
        for node in nodes:
            node_name = node.metadata.name
            allocatable = node.status.allocatable or {}
            total = ResourceQuantity(
                cpu_cores=parse_cpu(allocatable.get("cpu")),
                memory_bytes=parse_memory(allocatable.get("memory")),
                npu=parse_number(allocatable.get(npu_resource_name)),
            )
            node_resources[node_name] = ResourceNodeInfo(
                node_name=node_name,
                total=total,
                used=ResourceQuantity(),
                available=total,
            )
        return node_resources

    def _finalize_node_resources(self, node_resources: dict[str, ResourceNodeInfo]) -> list[ResourceNodeInfo]:
        for node_resource in node_resources.values():
            node_resource.available = ResourceQuantity(
                cpu_cores=max(node_resource.total.cpu_cores - node_resource.used.cpu_cores, 0),
                memory_bytes=max(node_resource.total.memory_bytes - node_resource.used.memory_bytes, 0),
                npu=max(node_resource.total.npu - node_resource.used.npu, 0),
            )
        return sorted(node_resources.values(), key=lambda node_resource: node_resource.node_name)

    def _pod_requests(self, pod: Any, npu_resource_name: str) -> ResourceQuantity:
        regular = ResourceQuantity()
        init_max = ResourceQuantity()

        for container in pod.spec.containers or []:
            requests = container.resources.requests or {}
            regular.cpu_cores += parse_cpu(requests.get("cpu"))
            regular.memory_bytes += parse_memory(requests.get("memory"))
            regular.npu += parse_number(requests.get(npu_resource_name))

        for container in pod.spec.init_containers or []:
            requests = container.resources.requests or {}
            init_max.cpu_cores = max(init_max.cpu_cores, parse_cpu(requests.get("cpu")))
            init_max.memory_bytes = max(init_max.memory_bytes, parse_memory(requests.get("memory")))
            init_max.npu = max(init_max.npu, parse_number(requests.get(npu_resource_name)))

        effective = ResourceQuantity(
            cpu_cores=max(regular.cpu_cores, init_max.cpu_cores),
            memory_bytes=max(regular.memory_bytes, init_max.memory_bytes),
            npu=max(regular.npu, init_max.npu),
        )

        overhead = pod.spec.overhead or {}
        effective.cpu_cores += parse_cpu(overhead.get("cpu"))
        effective.memory_bytes += parse_memory(overhead.get("memory"))
        effective.npu += parse_number(overhead.get(npu_resource_name))
        return effective

    def _pod_info(self, cluster: KubernetesClusterConfig, pod: Any, requests: ResourceQuantity) -> ResourcePodInfo:
        status = pod.status
        started_at = getattr(status, "start_time", None) if status else None
        finished_at = self._finished_at(status)
        created_at = pod.metadata.creation_timestamp if pod.metadata else None
        duration_seconds = None
        if started_at:
            end_time = finished_at or datetime.now(UTC)
            duration_seconds = int((end_time - started_at).total_seconds())

        return ResourcePodInfo(
            cluster_id=cluster.id,
            cluster_name=cluster.name,
            namespace=pod.metadata.namespace,
            name=pod.metadata.name,
            phase=status.phase if status else None,
            status=self._container_status_summary(status),
            node_name=pod.spec.node_name,
            labels=pod.metadata.labels or {},
            created_at=created_at,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration_seconds,
            requests=requests,
            containers=[container.name for container in pod.spec.containers or []],
        )

    def _finished_at(self, status: Any) -> datetime | None:
        if not status or not status.container_statuses:
            return None
        finished_times = []
        for container_status in status.container_statuses:
            terminated = getattr(container_status.state, "terminated", None)
            if terminated and terminated.finished_at:
                finished_times.append(terminated.finished_at)
        return max(finished_times) if finished_times else None

    def _container_status_summary(self, status: Any) -> str | None:
        if not status or not status.container_statuses:
            return None
        waiting_reasons = []
        for container_status in status.container_statuses:
            waiting = getattr(container_status.state, "waiting", None)
            if waiting and waiting.reason:
                waiting_reasons.append(waiting.reason)
        return ", ".join(waiting_reasons) if waiting_reasons else None

    def _add_quantity(self, left: ResourceQuantity, right: ResourceQuantity) -> ResourceQuantity:
        return ResourceQuantity(
            cpu_cores=left.cpu_cores + right.cpu_cores,
            memory_bytes=left.memory_bytes + right.memory_bytes,
            npu=left.npu + right.npu,
        )


def parse_cpu(value: str | int | float | None) -> float:
    if value is None:
        return 0
    text = str(value)
    if text.endswith("m"):
        return float(Decimal(text[:-1]) / Decimal(1000))
    return float(Decimal(text))


def parse_memory(value: str | int | float | None) -> int:
    if value is None:
        return 0
    text = str(value)
    units = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "Pi": 1024**5,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
        "P": 1000**5,
    }
    for suffix, multiplier in units.items():
        if text.endswith(suffix):
            return int(Decimal(text[: -len(suffix)]) * multiplier)
    return int(Decimal(text))


def parse_number(value: str | int | float | None) -> float:
    if value is None:
        return 0
    return float(Decimal(str(value)))
