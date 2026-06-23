import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAdminUser, DbSession
from app.schemas.issue_diagnosis import IssueDiagnosisRequest
from app.services.issue_diagnosis import IssueDiagnosisService

logger = logging.getLogger(__name__)

router = APIRouter()

service = IssueDiagnosisService()


@router.post("/diagnose", summary="问题定位诊断（SSE流式响应）")
async def diagnose(
    request: IssueDiagnosisRequest,
    current_user: CurrentAdminUser,
    db: DbSession,
):
    async def event_stream():
        async for event_data in service.stream_diagnose(
            data_source_type=request.data_source_type,
            job_id=request.job_id,
            run_id=request.run_id,
            commit_sha=request.commit_sha,
            user_prompt=request.user_prompt,
            db=db,
        ):
            event = event_data.get("event", "chunk")
            data = event_data.get("data", {})

            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

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
    days_back: int = 7,
    current_user: CurrentAdminUser,
    db: DbSession,
):
    try:
        jobs = await service.get_failed_ci_jobs(days_back, db)
        return jobs
    except Exception as e:
        logger.error(f"Failed to get CI jobs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/data-sources/commits", summary="获取最近的commit列表")
async def get_recent_commits(
    days_back: int = 7,
    current_user: CurrentAdminUser,
    db: DbSession,
):
    try:
        commits = await service.get_recent_commits(days_back, db)
        return commits
    except Exception as e:
        logger.error(f"Failed to get commits: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
