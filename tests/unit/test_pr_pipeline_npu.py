from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pr_pipeline.pr_pipeline_service import PRPipelineService
from infrastructure.persistence.models import CIJob


def make_job(
    *,
    job_name: str,
    runner_labels: str,
    run_id: int = 2,
    job_id: int = 1,
    status: str = "queued",
    conclusion: str | None = None,
) -> CIJob:
    return CIJob(
        job_id=job_id,
        run_id=run_id,
        workflow_name="PR Test",
        job_name=job_name,
        runner_labels=runner_labels,
        runner_name=None,
        status=status,
        conclusion=conclusion,
    )


def test_npu_cards_are_read_from_selected_test_runner_label():
    job = make_job(
        job_name="selected-tests a3-4 card",
        runner_labels='["linux-aarch64-a3-4"]',
    )

    assert PRPipelineService._npu_cards_for_job(job) == 4


def test_zero_and_cpu_labels_do_not_create_npu_demand():
    cpu_job = make_job(
        job_name="selected-tests cpu",
        runner_labels='["linux-amd64-cpu-8-hk"]',
    )
    dynamic_job = make_job(
        job_name="multi-node test",
        runner_labels='["linux-aarch64-a3-0"]',
    )

    assert PRPipelineService._npu_cards_for_job(cpu_job) == 0
    assert PRPipelineService._npu_cards_for_job(dynamic_job) == 0


def test_a3_560t_is_not_mistaken_for_560_npu_cards():
    job = make_job(
        job_name="selected-tests a3-560t",
        runner_labels='["linux-aarch64-a3-560t"]',
    )

    assert PRPipelineService._npu_cards_for_job(job) == 0


def test_only_unfinished_jobs_need_npu_capacity():
    queued = make_job(
        job_name="selected-tests a3-4 card",
        runner_labels='["linux-aarch64-a3-4"]',
        status="queued",
    )
    running = make_job(
        job_name="selected-tests a3-4 card",
        runner_labels='["linux-aarch64-a3-4"]',
        status="in_progress",
    )
    skipped = make_job(
        job_name="selected-tests a3-4 card",
        runner_labels='["linux-aarch64-a3-4"]',
        status="completed",
        conclusion="skipped",
    )

    assert PRPipelineService._job_has_pending_npu(queued)
    assert PRPipelineService._job_has_pending_npu(running)
    assert not PRPipelineService._job_has_pending_npu(skipped)


class FakeResult:
    def __init__(self, rows: list[object]):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


@pytest.mark.asyncio
async def test_npu_stats_use_latest_pr_run_and_subtract_allocated_pods():
    pr = SimpleNamespace(pr_number=42, head_sha="sha-42", ci_workflow_run_id=None)
    latest_pr_run = SimpleNamespace(run_id=100, head_sha="sha-42", event="pull_request")
    old_pr_run = SimpleNamespace(run_id=98, head_sha="sha-42", event="pull_request")
    nightly_run = SimpleNamespace(run_id=99, head_sha="sha-42", event="schedule")

    jobs = [
        make_job(
            job_id=1001,
            run_id=100,
            job_name="selected-tests a3-4 card",
            runner_labels='["linux-aarch64-a3-4"]',
            status="queued",
        ),
        make_job(
            job_id=1002,
            run_id=100,
            job_name="selected-tests a3-2 card",
            runner_labels='["linux-aarch64-a3-2"]',
            status="in_progress",
        ),
        make_job(
            job_id=1003,
            run_id=100,
            job_name="selected-tests a3-8 card",
            runner_labels='["linux-aarch64-a3-8"]',
            status="completed",
            conclusion="success",
        ),
        make_job(
            job_id=9801,
            run_id=98,
            job_name="old selected-tests a3-8 card",
            runner_labels='["linux-aarch64-a3-8"]',
            status="queued",
        ),
        make_job(
            job_id=9901,
            run_id=99,
            job_name="nightly selected-tests a3-8 card",
            runner_labels='["linux-aarch64-a3-8"]',
            status="queued",
        ),
    ]
    metrics = SimpleNamespace(
        cluster_id=1,
        top_pods_json=[
            {"name": "pr-42-a", "namespace": "ci", "phase": "Running", "pr_number": 42, "npu": 4},
            {"name": "unrelated", "namespace": "ci", "phase": "Running", "pr_number": 7, "npu": 8},
        ],
    )
    db = AsyncMock()
    db.execute.side_effect = [
        FakeResult([latest_pr_run, old_pr_run, nightly_run]),
        FakeResult(jobs),
        FakeResult([metrics]),
    ]

    stats = await PRPipelineService()._get_npu_stats(db, [pr])

    assert stats[42] == {
        "planned_npu": 6.0,
        "allocated_npu": 4.0,
        "npu_demand": 2.0,
        "pending_npu_jobs": 2,
    }
