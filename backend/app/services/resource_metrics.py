import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KubernetesClusterConfig, ProjectDashboardConfig, ResourceNpuMetrics
from app.schemas.resource_metrics import RESOURCE_METRICS_CONFIG_KEY
from app.services.resource_dashboard import ResourceDashboardService

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {"interval_minutes": 1, "retention_days": 30}

TIME_RANGE_GRANULARITY = {
    "1h": 1,
    "24h": 5,
    "7d": 60,
    "30d": 360,
}

TIME_RANGE_DURATION = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class ResourceMetricsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def collect_snapshot(self) -> int:
        stmt = select(KubernetesClusterConfig).where(KubernetesClusterConfig.enabled.is_(True))
        result = await self.db.execute(stmt)
        clusters = list(result.scalars().all())

        if not clusters:
            logger.info("No enabled clusters, skipping metrics collection")
            return 0

        service = ResourceDashboardService()
        dashboard = await service.build_dashboard(clusters, include_pods=True)

        count = 0
        now = datetime.now(UTC)
        for cluster_summary in dashboard.clusters:
            if cluster_summary.error:
                logger.error(f"Cluster {cluster_summary.cluster_name} has error: {cluster_summary.error}, skipping")
                continue

            executing_pods = cluster_summary.executing_pods or []
            top_pods = sorted(executing_pods, key=lambda p: p.requests.npu, reverse=True)[:5]
            top_pods_data = [
                {
                    "name": p.name,
                    "namespace": p.namespace,
                    "npu": p.requests.npu,
                    "pr_number": p.pr_number,
                    "pr_url": p.pr_url,
                    "phase": p.phase,
                }
                for p in top_pods
            ]

            pr_numbers = [p.pr_number for p in executing_pods if p.pr_number]
            metric = ResourceNpuMetrics(
                cluster_id=cluster_summary.cluster_id,
                cluster_name=cluster_summary.cluster_name,
                npu_total=cluster_summary.total.npu,
                npu_used=cluster_summary.used.npu,
                npu_available=cluster_summary.available.npu,
                npu_utilization=round(cluster_summary.used.npu / cluster_summary.total.npu * 100, 2) if cluster_summary.total.npu > 0 else 0,
                executing_pods_count=cluster_summary.executing_pods_count,
                pr_count=len(set(pr_numbers)),
                top_pods_json=top_pods_data,
                collected_at=now,
            )
            self.db.add(metric)
            count += 1

        await self.db.commit()
        logger.info(f"Collected NPU metrics for {count} clusters")
        return count

    async def query_npu_metrics(
        self,
        cluster_ids: list[int] | None = None,
        time_range: str = "24h",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict:
        granularity_minutes = TIME_RANGE_GRANULARITY.get(time_range, 5)
        duration = TIME_RANGE_DURATION.get(time_range, timedelta(hours=24))

        if end_time is None:
            end_time = datetime.now(UTC)
        if start_time is None:
            start_time = end_time - duration

        cluster_query = select(KubernetesClusterConfig).where(KubernetesClusterConfig.enabled.is_(True))
        if cluster_ids:
            cluster_query = cluster_query.where(KubernetesClusterConfig.id.in_(cluster_ids))
        cluster_query = cluster_query.order_by(KubernetesClusterConfig.display_order.asc(), KubernetesClusterConfig.name.asc())
        cluster_result = await self.db.execute(cluster_query)
        clusters = list(cluster_result.scalars().all())

        result_clusters = []

        for cluster in clusters:
            stmt = select(ResourceNpuMetrics).where(
                ResourceNpuMetrics.cluster_id == cluster.id,
                ResourceNpuMetrics.collected_at >= start_time,
                ResourceNpuMetrics.collected_at <= end_time,
            ).order_by(ResourceNpuMetrics.collected_at.asc())

            metrics_result = await self.db.execute(stmt)
            raw_metrics = list(metrics_result.scalars().all())

            if granularity_minutes <= 1:
                aggregated = raw_metrics
            else:
                aggregated = self._aggregate_metrics(raw_metrics, granularity_minutes)

            points = [
                {
                    "collected_at": m.collected_at if hasattr(m, "collected_at") else m["collected_at"],
                    "npu_utilization": m.npu_utilization if hasattr(m, "npu_utilization") else m["npu_utilization"],
                    "npu_total": m.npu_total if hasattr(m, "npu_total") else m["npu_total"],
                    "npu_used": m.npu_used if hasattr(m, "npu_used") else m["npu_used"],
                    "npu_available": m.npu_available if hasattr(m, "npu_available") else m["npu_available"],
                    "executing_pods_count": m.executing_pods_count if hasattr(m, "executing_pods_count") else m["executing_pods_count"],
                    "pr_count": m.pr_count if hasattr(m, "pr_count") else m["pr_count"],
                    "top_pods": m.top_pods_json if hasattr(m, "top_pods_json") else m.get("top_pods", []),
                }
                for m in aggregated
            ]

            result_clusters.append({
                "cluster_id": cluster.id,
                "cluster_name": cluster.name,
                "metrics": points,
            })

        return {"clusters": result_clusters}

    def _aggregate_metrics(self, raw_metrics: list[ResourceNpuMetrics], granularity_minutes: int) -> list[dict]:
        if not raw_metrics:
            return []

        grouped: dict[str, list[ResourceNpuMetrics]] = {}
        for m in raw_metrics:
            bucket = self._time_bucket(m.collected_at, granularity_minutes)
            if bucket not in grouped:
                grouped[bucket] = []
            grouped[bucket].append(m)

        result = []
        for bucket_key in sorted(grouped.keys()):
            group = grouped[bucket_key]
            avg_utilization = sum(m.npu_utilization for m in group) / len(group)
            avg_pods_count = sum(m.executing_pods_count for m in group) / len(group)
            avg_pr_count = sum(m.pr_count for m in group) / len(group)
            last_metric = group[-1]

            result.append({
                "collected_at": last_metric.collected_at,
                "npu_utilization": round(avg_utilization, 2),
                "npu_total": last_metric.npu_total,
                "npu_used": last_metric.npu_used,
                "npu_available": last_metric.npu_available,
                "executing_pods_count": round(avg_pods_count),
                "pr_count": round(avg_pr_count),
                "top_pods": last_metric.top_pods_json or [],
            })

        return result

    def _time_bucket(self, dt: datetime, granularity_minutes: int) -> str:
        total_minutes = int(dt.timestamp()) // 60
        bucket = total_minutes // granularity_minutes
        return str(bucket)

    async def cleanup_old_metrics(self) -> int:
        config = await self._get_config()
        retention_days = config.get("retention_days", 30)
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        stmt = delete(ResourceNpuMetrics).where(ResourceNpuMetrics.collected_at < cutoff)
        result = await self.db.execute(stmt)
        await self.db.commit()

        deleted = result.rowcount
        logger.info(f"Cleaned up {deleted} NPU metrics older than {retention_days} days")
        return deleted

    async def get_config(self) -> dict:
        return await self._get_config()

    async def update_config(self, interval_minutes: int | None = None, retention_days: int | None = None) -> dict:
        current = await self._get_config()
        if interval_minutes is not None:
            current["interval_minutes"] = interval_minutes
        if retention_days is not None:
            current["retention_days"] = retention_days

        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == RESOURCE_METRICS_CONFIG_KEY
        )
        result = await self.db.execute(stmt)
        config_row = result.scalar_one_or_none()

        if config_row:
            config_row.config_value = current
            config_row.updated_at = datetime.now(UTC)
        else:
            config_row = ProjectDashboardConfig(
                config_key=RESOURCE_METRICS_CONFIG_KEY,
                config_value=current,
                description="NPU 指标采集配置",
            )
            self.db.add(config_row)

        await self.db.commit()
        return current

    async def _get_config(self) -> dict:
        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == RESOURCE_METRICS_CONFIG_KEY
        )
        result = await self.db.execute(stmt)
        config_row = result.scalar_one_or_none()
        if config_row and config_row.config_value:
            return dict(config_row.config_value)
        return dict(DEFAULT_CONFIG)