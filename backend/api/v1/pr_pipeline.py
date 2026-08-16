import logging

from fastapi import APIRouter, HTTPException, Query, status

from api.deps import CurrentAdminUser, CurrentUser, DbSession
from contracts.schemas.pr_pipeline import (
    PRPipelineContributorsResponse,
    PRPipelineHistoricalSyncRequest,
    PRPipelineKanban,
    PRPipelineListResponse,
    PRPipelineMetrics,
    PRPipelineOverview,
    PRPipelineSyncRequest,
    PRPipelineTrendsResponse,
    PullRequestResponse,
)
from infrastructure.core.config import settings
from pr_pipeline.pr_pipeline_service import PRPipelineService

logger = logging.getLogger(__name__)

router = APIRouter()

service = PRPipelineService()

OWNER = settings.GITHUB_OWNER
REPO = settings.GITHUB_REPO


@router.get("/overview", response_model=PRPipelineOverview)
async def get_overview(
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
):
    return await service.get_overview(db, OWNER, REPO, days)


@router.get("/kanban", response_model=PRPipelineKanban)
async def get_kanban(
    db: DbSession,
    current_user: CurrentUser,
    state: str | None = Query(default="open"),
    include_draft: bool = Query(default=False),
    limit_per_stage: int = Query(default=20, ge=1, le=100),
):
    return await service.get_kanban(db, OWNER, REPO, state, include_draft, limit_per_stage)


@router.get("/list", response_model=PRPipelineListResponse)
async def get_list(
    db: DbSession,
    current_user: CurrentUser,
    state: str | None = Query(default=None),
    author: str | None = Query(default=None),
    pipeline_stage: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    ci_status: str | None = Query(default=None),
    is_draft: bool | None = Query(default=None),
    base_branch: str | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    label: str | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="updated_at"),
    sort_order: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await service.get_list(
        db, OWNER, REPO,
        state=state, author=author, pipeline_stage=pipeline_stage,
        review_status=review_status, ci_status=ci_status,
        is_draft=is_draft, base_branch=base_branch,
        date_from=date_from, date_to=date_to,
        label=label, search=search,
        sort_by=sort_by, sort_order=sort_order,
        page=page, page_size=page_size,
    )


@router.get("/metrics", response_model=PRPipelineMetrics)
async def get_metrics(
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
):
    return await service.get_metrics(db, OWNER, REPO, days)


@router.get("/contributors", response_model=PRPipelineContributorsResponse)
async def get_contributors(
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
    type: str | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    company: str | None = Query(default=None),
    sort_by: str = Query(default="pr_count"),
):
    return await service.get_contributors(db, OWNER, REPO, days, type, skip, limit, company, sort_by)


@router.get("/trends", response_model=PRPipelineTrendsResponse)
async def get_trends(
    db: DbSession,
    current_user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
):
    return await service.get_trends(db, OWNER, REPO, days)


@router.post("/sync")
async def sync_pr_pipeline(
    current_user: CurrentAdminUser,
    request: PRPipelineSyncRequest | None = None,
):
    """Enqueue a durable PR pipeline synchronization task."""
    from uuid import uuid4

    from infrastructure.db.base import SessionLocal
    from infrastructure.tasks.task_manager import TaskManager

    days_back = request.days_back if request else 7
    async with SessionLocal() as db:
        task_id = await TaskManager.create_task(
            db,
            "pr_sync",
            {"days_back": days_back},
            f"pr_sync:manual:{uuid4()}",
            required_capability="python",
            priority=10,
        )
        await db.commit()
    if task_id is None:
        return {"message": "An equivalent PR sync task is already queued", "running": False}
    return {"message": f"PR sync task {task_id} queued", "task_id": task_id, "running": True}


@router.get("/sync/status")
async def sync_status():
    """Return the latest durable PR sync task status."""
    from sqlalchemy import text

    from infrastructure.db.base import SessionLocal

    async with SessionLocal() as db:
        row = (await db.execute(text("""
            SELECT
                id,
                status,
                last_error,
                created_at,
                CASE
                    WHEN status IN ('completed', 'failed', 'dead') THEN updated_at
                    ELSE NULL
                END AS completed_at
            FROM collection_tasks
            WHERE task_type = 'pr_sync'
            ORDER BY id DESC
            LIMIT 1
        """))).mappings().first()
    if not row:
        return {"running": False, "task_id": None, "status": "idle"}
    return {
        "running": row["status"] in {"pending", "running"},
        "task_id": row["id"],
        "status": row["status"],
        "error": row["last_error"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }


@router.post("/historical-sync")
async def historical_sync_pr_pipeline(
    db: DbSession,
    current_user: CurrentAdminUser,
    request: PRPipelineHistoricalSyncRequest | None = None,
):
    phases = request.phases if request else ["A", "B"]
    months_back = request.months_back if request else 3

    from uuid import uuid4

    from infrastructure.tasks.task_manager import TaskManager

    task_id = await TaskManager.create_task(
        db,
        "pr_historical_sync",
        {"phases": phases, "months_back": months_back},
        f"pr_historical_sync:manual:{uuid4()}",
        required_capability="python",
        priority=10,
    )
    await db.commit()
    return {
        "message": "Historical PR sync task queued",
        "task_id": task_id,
        "running": task_id is not None,
    }


@router.get("/{pr_number}", response_model=PullRequestResponse)
async def get_pr_detail(
    db: DbSession,
    current_user: CurrentUser,
    pr_number: int,
):
    result = await service.get_pr_detail(db, OWNER, REPO, pr_number)
    if not result:
        raise HTTPException(status_code=404, detail=f"PR #{pr_number} not found")
    return result


@router.post("/{pr_number}/diagnose")
async def diagnose_pr(
    pr_number: int,
    current_user: CurrentUser,
    db: DbSession,
):
    """AI 诊断指定 PR"""
    try:
        from pr_pipeline.pr_diagnosis import PRDiagnosisService
        diag_service = PRDiagnosisService(db)
        result = await diag_service.diagnose(pr_number)
        # Save to history
        try:
            from infrastructure.persistence.models import IssueDiagnosisHistory
            history = IssueDiagnosisHistory(
                user_id=current_user.id,
                diagnosis_type="pr_pipeline",
                target_id=str(pr_number),
                target_label=result.get("pr_title", f"PR #{pr_number}"),
                report_content=result.get("report", ""),
                model_used=result.get("model", ""),
                duration_seconds=result.get("duration_seconds", 0),
                status="success",
            )
            db.add(history)
            await db.commit()
            await db.refresh(history)
            result["history_id"] = history.id
        except Exception as e:
            logger.warning(f"Failed to save diagnosis history: {e}")
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"PR diagnosis failed for #{pr_number}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="诊断失败，请稍后重试或检查 LLM 配置"
        )
