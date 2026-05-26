from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CommitChangeType(StrEnum):
    FEATURE = "Feature"
    BUGFIX = "Bugfix"
    REFACTOR = "Refactor"
    COMMON = "Common"
    TEST = "Test"
    CI = "CI"
    OTHER = "Other"


class CommitAnalysisStatus(StrEnum):
    NOT_ANALYZED = "未分析"
    ANALYZED = "已分析"
    CLOSED = "已闭环"


class CommitAnalysisUpdate(BaseModel):
    what_commit_did: str | None = None
    change_type: CommitChangeType | None = None
    affects_api: bool | None = None
    vllm_ascend_impact: str | None = None
    next_plan: str | None = None
    planned_closure_time: str | None = None
    actual_closure_time: str | None = None


class CommitAnalysisAssignRequest(BaseModel):
    assignee: str = Field(..., max_length=100)


class CommitAnalysisBatchRequest(BaseModel):
    shas: list[str] = Field(default_factory=list, max_length=500)


class CommitAnalysisResponse(BaseModel):
    project: str
    sha: str
    assignee: str | None = None
    what_commit_did: str | None = None
    change_type: CommitChangeType | None = None
    affects_api: bool | None = None
    vllm_ascend_impact: str | None = None
    next_plan: str | None = None
    planned_closure_time: str | None = None
    actual_closure_time: str | None = None
    created_at: str | None = None
    created_by: str | None = None
    updated_at: str | None = None
    updated_by: str | None = None
    status: CommitAnalysisStatus
    can_edit: bool


class CommitAnalysisBatchItem(BaseModel):
    sha: str
    assignee: str | None = None
    change_type: CommitChangeType | None = None
    status: CommitAnalysisStatus


class CommitAnalysisBatchResponse(BaseModel):
    project: str
    analyses: dict[str, CommitAnalysisBatchItem]
    filters: dict[str, list[Any]]
