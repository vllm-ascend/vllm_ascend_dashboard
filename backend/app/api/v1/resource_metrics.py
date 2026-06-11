from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAdminUser, CurrentSuperAdminUser, CurrentUser, DbSession
from app.schemas import (
    NpuMetricsResponse,
    ResourceMetricsConfigResponse,
    ResourceMetricsConfigUpdate,
)
from app.services.resource_metrics import ResourceMetricsService

router = APIRouter()


@router.get("/metrics/npu", response_model=NpuMetricsResponse)
async def get_npu_metrics(
    db: DbSession,
    current_user: CurrentUser,
    cluster_ids: Annotated[list[int] | None, Query()] = None,
    time_range: str = Query("24h", description="时间范围：1h/24h/7d/30d"),
    start_time: datetime | None = Query(None, description="起始时间（ISO8601）"),
    end_time: datetime | None = Query(None, description="结束时间（ISO8601）"),
):
    service = ResourceMetricsService(db)
    data = await service.query_npu_metrics(
        cluster_ids=cluster_ids,
        time_range=time_range,
        start_time=start_time,
        end_time=end_time,
    )
    return NpuMetricsResponse(
        clusters=[
            {
                "cluster_id": c["cluster_id"],
                "cluster_name": c["cluster_name"],
                "metrics": c["metrics"],
            }
            for c in data["clusters"]
        ]
    )


@router.get("/metrics/config", response_model=ResourceMetricsConfigResponse)
async def get_metrics_config(
    db: DbSession,
    current_user: CurrentAdminUser,
):
    service = ResourceMetricsService(db)
    config = await service.get_config()
    return ResourceMetricsConfigResponse(**config)


@router.put("/metrics/config", response_model=ResourceMetricsConfigResponse)
async def update_metrics_config(
    db: DbSession,
    current_user: CurrentSuperAdminUser,
    config_update: ResourceMetricsConfigUpdate,
):
    service = ResourceMetricsService(db)
    updated = await service.update_config(
        interval_minutes=config_update.interval_minutes,
        retention_days=config_update.retention_days,
    )

    from app.services.scheduler import get_scheduler
    scheduler = get_scheduler()
    scheduler.update_resource_metrics_schedule(updated["interval_minutes"])

    return ResourceMetricsConfigResponse(**updated)