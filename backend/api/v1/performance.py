"""
性能数据 API 路由
Phase 1: 基础版本，提供数据查询接口
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from api.deps import DbSession
from contracts.schemas import Message, PerformanceComparison, PerformanceDataResponse
from infrastructure.persistence.models import PerformanceData

router = APIRouter()


@router.get("", response_model=list[PerformanceDataResponse])
async def list_performance_data(
    db: DbSession,
    model_name: str | None = None,
    hardware: str | None = None,
    test_type: str | None = None,
    vllm_version: str | None = None,
    limit: int = Query(100, ge=1, le=500)
):
    """获取性能数据列表"""
    stmt = select(PerformanceData)

    if model_name:
        stmt = stmt.where(PerformanceData.model_name == model_name)
    if hardware:
        stmt = stmt.where(PerformanceData.hardware == hardware)
    if test_type:
        stmt = stmt.where(PerformanceData.test_type == test_type)
    if vllm_version:
        stmt = stmt.where(PerformanceData.vllm_version == vllm_version)

    stmt = stmt.order_by(
        PerformanceData.timestamp.desc()
    ).limit(limit)

    result = await db.execute(stmt)
    results = result.scalars().all()

    return results


@router.get("/{data_id}", response_model=PerformanceDataResponse)
async def get_performance_data(
    db: DbSession,
    data_id: int
):
    """获取单次测试详情"""
    stmt = select(PerformanceData).where(PerformanceData.id == data_id)
    result = await db.execute(stmt)
    data = result.scalar_one_or_none()

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="性能数据不存在",
        )

    return data


@router.get("/trends")
async def get_performance_trends(
    db: DbSession,
    model_name: str,
    hardware: str,
    test_type: str,
    days: int = Query(30, ge=1, le=365)
):
    """获取性能趋势

    Phase 3 实现
    """
    return {
        "message": "Not implemented in Phase 1",
        "params": {
            "model_name": model_name,
            "hardware": hardware,
            "test_type": test_type,
            "days": days,
        }
    }


@router.get("/compare", response_model=PerformanceComparison)
async def compare_performance(
    db: DbSession,
    model_name: str,
    hardware: str,
    baseline_date: str,
    compare_date: str
):
    """性能对比

    Phase 3 实现
    """
    return {
        "baseline": {"date": baseline_date, "throughput": 0, "ttft_median_ms": 0},
        "current": {"date": compare_date, "throughput": 0, "ttft_median_ms": 0},
        "change": {"throughput": "0%", "ttft_median_ms": "0%"},
    }


@router.post("/upload", response_model=Message)
async def upload_performance_data():
    """手动上传性能数据

    Phase 3 实现
    """
    return {"message": "Not implemented in Phase 1"}


@router.post("/sync", response_model=Message)
async def trigger_sync():
    """触发数据同步

    Phase 3 实现
    """
    return {"message": "Not implemented in Phase 1"}
