"""
PR Pipeline Kanban 相关的 Pydantic Schemas
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


class PullRequestBase(BaseModel):
    pr_number: int
    owner: str
    repo: str
    title: str
    author: str
    author_avatar_url: str | None = None
    html_url: str | None = None
    state: str
    is_draft: bool = False
    labels: list[str] = []
    head_branch: str | None = None
    head_sha: str | None = None
    base_branch: str | None = None
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    pipeline_stage: str | None = None
    review_status: str | None = None
    reviewers: list[dict[str, Any]] = []
    ci_status: str | None = None
    ci_workflow_run_id: int | None = None


class PullRequestResponse(PullRequestBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    first_review_at: datetime | None = None
    first_approved_at: datetime | None = None
    ci_started_at: datetime | None = None
    ci_completed_at: datetime | None = None
    merged_at: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    data: dict[str, Any] | None = None

    @computed_field
    @property
    def time_to_first_review_hours(self) -> float | None:
        if self.first_review_at and self.created_at:
            delta = self.first_review_at - self.created_at
            return round(delta.total_seconds() / 3600, 1)
        return None

    @computed_field
    @property
    def time_to_merge_hours(self) -> float | None:
        if self.merged_at and self.created_at:
            delta = self.merged_at - self.created_at
            return round(delta.total_seconds() / 3600, 1)
        return None

    @computed_field
    @property
    def time_to_ci_hours(self) -> float | None:
        if self.ci_started_at and self.created_at:
            delta = self.ci_started_at - self.created_at
            return round(delta.total_seconds() / 3600, 1)
        return None

    @computed_field
    @property
    def ci_duration_hours(self) -> float | None:
        if self.ci_completed_at and self.ci_started_at:
            delta = self.ci_completed_at - self.ci_started_at
            return round(delta.total_seconds() / 3600, 1)
        return None

    @computed_field
    @property
    def time_to_approval_hours(self) -> float | None:
        if self.first_approved_at and self.created_at:
            delta = self.first_approved_at - self.created_at
            return round(delta.total_seconds() / 3600, 1)
        return None


class PRPipelineStageDistribution(BaseModel):
    submitted: int = 0
    reviewing: int = 0
    approved: int = 0
    ci_running: int = 0
    ci_passed: int = 0
    ci_failed: int = 0
    merging: int = 0
    merged: int = 0
    closed: int = 0


class PRPipelineOverview(BaseModel):
    open_count: int
    merged_count: int
    closed_count: int
    draft_count: int
    backlog_index: float
    backlog_level: str
    merge_rate: float
    avg_time_to_first_review_hours: float | None = None
    avg_time_to_merge_hours: float | None = None
    pipeline_stage_distribution: PRPipelineStageDistribution
    recent_opened_count: int = 0
    recent_merged_count: int = 0
    last_sync_at: datetime | None = None


class PRPipelinePercentileMetric(BaseModel):
    p50: float | None = None
    p90: float | None = None
    avg: float | None = None
    count: int = 0


class PRPipelineMetrics(BaseModel):
    first_response_hours: PRPipelinePercentileMetric
    review_to_approval_hours: PRPipelinePercentileMetric
    ci_duration_hours: PRPipelinePercentileMetric
    merge_hours: PRPipelinePercentileMetric
    total_cycle_hours: PRPipelinePercentileMetric
    merge_rate: float = 0.0
    backlog_index: float = 0.0
    survival_distribution: list[dict[str, Any]] = []


class PRPipelineContributor(BaseModel):
    username: str
    avatar_url: str | None = None
    type: str
    pr_count: int = 0
    review_count: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    avg_first_response_hours: float | None = None
    merged_count: int = 0


class PRPipelineKanban(BaseModel):
    submitted: list[PullRequestResponse] = []
    reviewing: list[PullRequestResponse] = []
    approved: list[PullRequestResponse] = []
    ci_running: list[PullRequestResponse] = []
    ci_passed: list[PullRequestResponse] = []
    ci_failed: list[PullRequestResponse] = []
    merging: list[PullRequestResponse] = []
    merged: list[PullRequestResponse] = []
    closed: list[PullRequestResponse] = []


class PRPipelineListFilter(BaseModel):
    state: str | None = None
    author: str | None = None
    pipeline_stage: str | None = None
    review_status: str | None = None
    ci_status: str | None = None
    is_draft: bool | None = None
    base_branch: str | None = None
    date_from: str | None = None
    date_to: str | None = None


class PRPipelineListResponse(BaseModel):
    total: int
    items: list[PullRequestResponse]
    page: int
    page_size: int


class PRPipelineTrendPoint(BaseModel):
    date: str
    opened: int = 0
    merged: int = 0
    closed: int = 0
    open_total: int = 0


class PRPipelineTrendsResponse(BaseModel):
    trends: list[PRPipelineTrendPoint]
    period_days: int


class PRPipelineSyncRequest(BaseModel):
    days_back: int = Field(default=7, description="同步最近 N 天的数据")


class PRPipelineHistoricalSyncRequest(BaseModel):
    phases: list[str] = Field(default=["A", "B"], description="执行阶段: A=Open PRs, B=Recent Merged/Closed, C=Full history")
    months_back: int = Field(default=3, description="Phase B/C 回溯月数")
