from datetime import date as DateType

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentAdminUser, CurrentSuperAdminUser, CurrentUser, DbSession
from app.schemas.commit_analysis import (
    CommitAnalysisAssignRequest,
    CommitAnalysisBatchItem,
    CommitAnalysisBatchRequest,
    CommitAnalysisBatchResponse,
    CommitAnalysisResponse,
    CommitAnalysisStatus,
    CommitAnalysisUpdate,
    CommitChangeType,
)
from app.services.commit_analysis_file_store import CommitAnalysisFileStore
from app.services.commit_analysis_summary import CommitAnalysisSummaryService

router = APIRouter()


def is_admin(user: CurrentUser) -> bool:
    return user.role in ["admin", "super_admin"]


def can_edit(user: CurrentUser, analysis: dict) -> bool:
    return is_admin(user) or analysis.get("assignee") == user.username


def to_response(store: CommitAnalysisFileStore, user: CurrentUser, analysis: dict) -> CommitAnalysisResponse:
    return CommitAnalysisResponse(
        **analysis,
        status=store.derive_status(analysis),
        can_edit=can_edit(user, analysis),
    )


def build_batch_item(store: CommitAnalysisFileStore, sha: str, analysis: dict) -> CommitAnalysisBatchItem:
    return CommitAnalysisBatchItem(
        sha=sha,
        assignee=analysis.get("assignee"),
        change_type=analysis.get("change_type"),
        status=store.derive_status(analysis),
    )


@router.get("/{project}/{sha}", response_model=CommitAnalysisResponse)
async def get_commit_analysis(
    project: str,
    sha: str,
    current_user: CurrentUser,
):
    try:
        store = CommitAnalysisFileStore()
        analysis = await store.load_analysis(project, sha)
        return to_response(store, current_user, analysis)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{project}/batch", response_model=CommitAnalysisBatchResponse)
async def batch_get_commit_analysis(
    project: str,
    request: CommitAnalysisBatchRequest,
    current_user: CurrentUser,
):
    try:
        store = CommitAnalysisFileStore()
        unique_shas = list(dict.fromkeys(request.shas))
        analyses = await store.load_batch(project, unique_shas)
        batch_items = {
            sha: build_batch_item(store, sha, analysis)
            for sha, analysis in analyses.items()
        }
        assignees = sorted({item.assignee for item in batch_items.values() if item.assignee})

        return CommitAnalysisBatchResponse(
            project=project,
            analyses=batch_items,
            filters={
                "assignees": assignees,
                "change_types": [item.value for item in CommitChangeType],
                "statuses": [item.value for item in CommitAnalysisStatus],
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{project}/{sha}/claim", response_model=CommitAnalysisResponse)
async def claim_commit_analysis(
    project: str,
    sha: str,
    current_user: CurrentUser,
):
    try:
        store = CommitAnalysisFileStore()
        analysis = await store.load_analysis(project, sha)
        assignee = analysis.get("assignee")

        if assignee and assignee != current_user.username:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Commit 已被其他责任人认领")

        now = store.now()
        if not assignee:
            analysis["assignee"] = current_user.username
            analysis["created_at"] = analysis.get("created_at") or now
            analysis["created_by"] = analysis.get("created_by") or current_user.username
            analysis["updated_at"] = now
            analysis["updated_by"] = current_user.username
            analysis = await store.save_analysis(project, sha, analysis)

        return to_response(store, current_user, analysis)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{project}/{sha}/ai-summary/regenerate", response_model=CommitAnalysisResponse)
async def regenerate_commit_ai_summary(
    project: str,
    sha: str,
    current_user: CurrentSuperAdminUser,
    db: DbSession,
    date: str | None = Query(default=None),
    llm_provider: str | None = Query(default=None),
):
    try:
        data_date = DateType.fromisoformat(date) if date else None
        service = CommitAnalysisSummaryService(db)
        analysis = await service.generate_summary(
            project=project,
            sha=sha,
            username=current_user.username,
            data_date=data_date,
            llm_provider=llm_provider,
        )
        store = CommitAnalysisFileStore()
        return to_response(store, current_user, analysis)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{project}/{sha}/assign", response_model=CommitAnalysisResponse)
async def assign_commit_analysis(
    project: str,
    sha: str,
    request: CommitAnalysisAssignRequest,
    current_user: CurrentAdminUser,
):
    try:
        store = CommitAnalysisFileStore()
        analysis = await store.load_analysis(project, sha)
        now = store.now()

        analysis["assignee"] = request.assignee.strip() or None
        analysis["created_at"] = analysis.get("created_at") or now
        analysis["created_by"] = analysis.get("created_by") or current_user.username
        analysis["updated_at"] = now
        analysis["updated_by"] = current_user.username
        analysis = await store.save_analysis(project, sha, analysis)

        return to_response(store, current_user, analysis)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put("/{project}/{sha}", response_model=CommitAnalysisResponse)
async def update_commit_analysis(
    project: str,
    sha: str,
    request: CommitAnalysisUpdate,
    current_user: CurrentUser,
):
    try:
        store = CommitAnalysisFileStore()
        analysis = await store.load_analysis(project, sha)

        if not can_edit(current_user, analysis):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

        now = store.now()
        update_data = request.model_dump(exclude_unset=True)
        analysis.update(update_data)
        analysis["created_at"] = analysis.get("created_at") or now
        analysis["created_by"] = analysis.get("created_by") or current_user.username
        analysis["updated_at"] = now
        analysis["updated_by"] = current_user.username
        analysis = await store.save_analysis(project, sha, analysis)

        return to_response(store, current_user, analysis)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
