from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class TestHealthScore(BaseModel):
    overall: float
    pass_rate: float
    stability: float
    reliability: float
    timeliness: float
    coverage: float | None = None
    level: str


class TestCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_name: str
    test_suite: str
    module_name: str | None = None
    test_type: str
    category: str | None = None
    hardware: str | None = None
    card_count: int | None = None
    file_path: str | None = None
    class_name: str | None = None
    owner: str | None = None
    owner_email: str | None = None
    inference_confidence: float = 0.0
    data_granularity: str = "file_level"
    is_flaky: bool = False
    flaky_rate: float = 0.0
    flaky_evidence_count: int = 0
    pass_rate_7d: float | None = None
    pass_rate_30d: float | None = None
    avg_duration_seconds: float | None = None
    duration_p90_seconds: float | None = None
    last_pass_duration_seconds: float | None = None
    health_score: float | None = None
    health_level: str | None = None
    last_result: str | None = None
    last_run_at: datetime | None = None
    total_runs: int = 0


class TestRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    test_case_id: int
    result: str
    duration_seconds: float | None = None
    model_load_seconds: float | None = None
    test_exec_seconds: float | None = None
    failure_category: str | None = None
    failure_message: str | None = None
    flip_detected: bool = False
    workflow_name: str | None = None
    job_name: str | None = None
    ci_job_id: int | None = None
    ci_run_id: int | None = None
    head_sha: str | None = None
    event: str | None = None
    started_at: datetime | None = None


class TestSuiteResponse(BaseModel):
    suite_name: str
    test_type: str
    hardware: str | None = None
    card_count: int | None = None
    total_cases: int
    pass_rate: float
    health_score: float | None = None
    health_level: str | None = None
    flaky_cases: int
    avg_duration_seconds: float | None = None
    last_run_at: datetime | None = None


class TestOverviewResponse(BaseModel):
    health_score: TestHealthScore
    total_cases: int
    pass_rate_7d: float
    flaky_case_count: int
    attention_case_count: int
    avg_duration_p50: float | None = None
    suite_distribution: dict[str, int]
    result_distribution: dict[str, int]
    health_trend: list[dict]
    pass_rate_trend: list[dict]


class FlakyCaseDetail(BaseModel):
    test_name: str
    test_suite: str
    module_name: str | None = None
    owner: str | None = None
    flip_rate: float
    total_runs: int
    flip_count: int
    recent_results: list[str]
    suggested_action: str


class FailureCategoryBreakdown(BaseModel):
    product_bug: int
    test_bug: int
    infrastructure: int
    unknown: int
    total: int
    product_bug_ratio: float
    infrastructure_ratio: float
    noise_ratio: float


class OwnerMatrixItem(BaseModel):
    owner: str | None
    modules: list[str]
    total_cases: int
    pass_rate_7d: float | None = None
    flaky_cases: int
    pending_failures: int
    avg_fix_hours: float | None = None


class ModuleHealthItem(BaseModel):
    module_name: str
    owner: str | None
    total_cases: int
    pass_rate_7d: float | None = None
    flaky_count: int
    pending_failures: int
    health_score: float | None = None
    health_level: str | None = None


class TestBoardSyncRequest(BaseModel):
    days_back: int = 7
    force: bool = False


class FailureAnnotationRequest(BaseModel):
    test_run_id: int
    annotated_category: str
    annotated_by: str
