"""Test fixtures for PR Pipeline bug fix tests."""
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Ensure settings validation passes before any app imports
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("GITHUB_TOKEN", "github_pat_test_token_for_ci_tests")
os.environ.setdefault("GITHUB_OWNER", "vllm-ascend")
os.environ.setdefault("GITHUB_REPO", "vllm-ascend")

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Ensure backend/ is on sys.path so `app` is importable
backend_dir = str(Path(__file__).resolve().parent.parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.models import Base, CIResult, PullRequest  # noqa: E402


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite database with PullRequest and CIResult tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[PullRequest.__table__, CIResult.__table__]
            )
        )

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def make_pr(
    pr_number: int,
    owner: str = "vllm-ascend",
    repo: str = "vllm-ascend",
    state: str = "open",
    is_draft: bool = False,
    created_at: datetime | None = None,
    merged_at: datetime | None = None,
    closed_at: datetime | None = None,
    head_sha: str | None = None,
    ci_status: str | None = None,
    pipeline_stage: str | None = None,
    review_status: str | None = None,
    ci_started_at: datetime | None = None,
    ci_completed_at: datetime | None = None,
    author: str = "testuser",
) -> PullRequest:
    """Helper to create a PullRequest instance for testing."""
    now = datetime.now(UTC)
    return PullRequest(
        pr_number=pr_number,
        owner=owner,
        repo=repo,
        title=f"PR #{pr_number}",
        author=author,
        state=state,
        is_draft=is_draft,
        head_sha=head_sha,
        ci_status=ci_status,
        pipeline_stage=pipeline_stage,
        review_status=review_status,
        created_at=created_at or now,
        merged_at=merged_at,
        closed_at=closed_at,
        ci_started_at=ci_started_at,
        ci_completed_at=ci_completed_at,
        updated_at=now,
    )


def make_ci_result(
    run_id: int,
    head_sha: str,
    status: str = "completed",
    conclusion: str | None = "success",
    event: str = "pull_request",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> CIResult:
    """Helper to create a CIResult instance for testing."""
    now = datetime.now(UTC)
    return CIResult(
        workflow_name="test-workflow",
        run_id=run_id,
        run_number=1,
        status=status,
        conclusion=conclusion,
        event=event,
        branch="main",
        head_sha=head_sha,
        started_at=started_at or now,
        completed_at=completed_at or now,
        duration_seconds=60,
        hardware="A2",
        created_at=now,
        updated_at=now,
    )
