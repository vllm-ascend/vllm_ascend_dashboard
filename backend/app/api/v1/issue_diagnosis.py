import json
import logging
import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentAdminUser, DbSession
from app.schemas.issue_diagnosis import IssueDiagnosisRequest
from app.services.issue_diagnosis import IssueDiagnosisService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/diagnose", summary="问题定位诊断（SSE流式响应）")
async def diagnose(
    request: IssueDiagnosisRequest,
    current_user: CurrentAdminUser,
    db: DbSession,
    fastapi_request: Request,
):
    service = IssueDiagnosisService()

    async def event_stream():
        try:
            async for event_data in service.stream_diagnose(
                data_source_type=request.data_source_type,
                job_id=request.job_id,
                run_id=request.run_id,
                commit_sha=request.commit_sha,
                user_prompt=request.user_prompt,
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
    current_user: CurrentAdminUser,
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
