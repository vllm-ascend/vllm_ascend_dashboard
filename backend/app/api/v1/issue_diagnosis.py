import json
import logging
import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAdminUser, CurrentUser, DbSession
from app.schemas.issue_diagnosis import IssueDiagnosisRequest
from app.services.issue_diagnosis import IssueDiagnosisService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/diagnose", summary="问题定位诊断（SSE流式响应）")
async def diagnose(
    request: IssueDiagnosisRequest,
    current_user: CurrentUser,
    db: DbSession,
    fastapi_request: Request,
):
    service = IssueDiagnosisService()

    async def event_stream():
        try:
            async for event_data in service.stream_diagnose(
                data_source_type=request.data_source_type,
                pr_number=request.pr_number,
                job_id=request.job_id,
                run_id=request.run_id,
                commit_sha=request.commit_sha,
                user_prompt=request.user_prompt,
                conversation_history=[message.model_dump() for message in request.conversation_history],
                db=db,
            ):
                if await fastapi_request.is_disconnected():
                    logger.info("Client disconnected, stopping diagnosis stream")
                    break

                event = event_data.get("event", "chunk")
                data = event_data.get("data", {})

                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            logger.info("Diagnosis stream cancelled (client disconnect)")
        except GeneratorExit:
            logger.info("Generator exited (client disconnect)")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/data-sources/ci-jobs", summary="获取失败的CI Job列表")
async def get_failed_ci_jobs(
    current_user: CurrentUser,
    db: DbSession,
    days_back: int = 7,
):
    try:
        service = IssueDiagnosisService()
        jobs = await service.get_failed_ci_jobs(days_back, db)
        return jobs
    except Exception as e:
        logger.error(f"Failed to get CI jobs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data-sources/commits", summary="获取最近的commit列表")
async def get_recent_commits(
    current_user: CurrentAdminUser,
    db: DbSession,
    days_back: int = 7,
):
    try:
        service = IssueDiagnosisService()
        commits = await service.get_recent_commits(days_back, db)
        return commits
    except Exception as e:
        logger.error(f"Failed to get commits: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history", summary="诊断历史记录")
async def list_diagnosis_history(
    current_user: CurrentUser,
    db: DbSession,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    diagnosis_type: str | None = Query(None),
    liked_only: bool = Query(False),
):
    """获取诊断历史记录列表"""
    from app.models import IssueDiagnosisHistory, User
    query = select(IssueDiagnosisHistory, User.username).outerjoin(User, IssueDiagnosisHistory.user_id == User.id)
    if diagnosis_type:
        query = query.where(IssueDiagnosisHistory.diagnosis_type == diagnosis_type)
    if liked_only:
        query = query.where(IssueDiagnosisHistory.is_liked == True)

    count_query = select(func.count(IssueDiagnosisHistory.id))
    if diagnosis_type:
        count_query = count_query.where(IssueDiagnosisHistory.diagnosis_type == diagnosis_type)
    if liked_only:
        count_query = count_query.where(IssueDiagnosisHistory.is_liked == True)
    total = (await db.execute(count_query)).scalar() or 0
    query = query.order_by(IssueDiagnosisHistory.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "username": username or "未知用户",
                "diagnosis_type": r.diagnosis_type,
                "target_id": r.target_id,
                "target_label": r.target_label,
                "model_used": r.model_used,
                "duration_seconds": r.duration_seconds,
                "status": r.status,
                "is_liked": r.is_liked,
                "like_count": r.like_count,
                "report_preview": (r.report_content[:200] + "...") if r.report_content and len(r.report_content) > 200 else r.report_content,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r, username in rows
        ],
    }


@router.get("/history/stats", summary="诊断统计")
async def diagnosis_stats(
    current_user: CurrentUser,
    db: DbSession,
):
    """获取诊断统计数据"""
    from app.models import IssueDiagnosisHistory
    from sqlalchemy import func as sql_func
    total = (await db.execute(select(sql_func.count(IssueDiagnosisHistory.id)))).scalar() or 0
    success = (await db.execute(select(sql_func.count(IssueDiagnosisHistory.id)).where(IssueDiagnosisHistory.status == "success"))).scalar() or 0
    liked = (await db.execute(select(sql_func.count(IssueDiagnosisHistory.id)).where(IssueDiagnosisHistory.is_liked == True))).scalar() or 0
    pr_count = (await db.execute(select(sql_func.count(IssueDiagnosisHistory.id)).where(IssueDiagnosisHistory.diagnosis_type == "pr_pipeline"))).scalar() or 0
    job_count = (await db.execute(select(sql_func.count(IssueDiagnosisHistory.id)).where(IssueDiagnosisHistory.diagnosis_type == "ci_job"))).scalar() or 0

    return {
        "total": total,
        "success_count": success,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "liked_count": liked,
        "pr_pipeline_count": pr_count,
        "ci_job_count": job_count,
    }


@router.get("/history/{history_id}", summary="获取诊断报告详情")
async def get_diagnosis_detail(
    history_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """获取完整诊断报告"""
    from app.models import IssueDiagnosisHistory
    stmt = select(IssueDiagnosisHistory).where(IssueDiagnosisHistory.id == history_id)
    record = (await db.execute(stmt)).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="诊断记录不存在")
    return {
        "id": record.id,
        "diagnosis_type": record.diagnosis_type,
        "target_id": record.target_id,
        "target_label": record.target_label,
        "report_content": record.report_content,
        "model_used": record.model_used,
        "duration_seconds": record.duration_seconds,
        "status": record.status,
        "is_liked": record.is_liked,
        "like_count": record.like_count,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.post("/history/{history_id}/like", summary="点赞/取消点赞")
async def toggle_like(
    history_id: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """切换点赞状态"""
    from app.models import IssueDiagnosisHistory
    stmt = select(IssueDiagnosisHistory).where(IssueDiagnosisHistory.id == history_id)
    record = (await db.execute(stmt)).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="诊断记录不存在")
    record.is_liked = not record.is_liked
    record.like_count = (record.like_count or 0) + (1 if record.is_liked else -1)
    if record.like_count < 0:
        record.like_count = 0
    await db.commit()
    return {"id": record.id, "is_liked": record.is_liked, "like_count": record.like_count}


@router.post("/history", summary="保存诊断记录")
async def save_diagnosis(
    body: dict,
    current_user: CurrentUser,
    db: DbSession,
):
    """保存诊断记录（用于流式诊断完成后前端调用）"""
    from app.models import IssueDiagnosisHistory
    record = IssueDiagnosisHistory(
        user_id=current_user.id,
        diagnosis_type=body.get("diagnosis_type", ""),
        target_id=body.get("target_id", ""),
        target_label=body.get("target_label", ""),
        report_content=body.get("report_content", ""),
        model_used=body.get("model_used", ""),
        duration_seconds=body.get("duration_seconds", 0),
        status=body.get("status", "success"),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "status": "saved"}
