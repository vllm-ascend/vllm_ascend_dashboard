import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, and_, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_board import TestCase, TestRun, TestSuiteSnapshot

logger = logging.getLogger(__name__)

CASE_WEIGHTS = {"pass_rate": 0.35, "stability": 0.30, "reliability": 0.20, "timeliness": 0.15}
SUITE_WEIGHTS = {"pass_rate": 0.30, "stability": 0.25, "reliability": 0.20, "timeliness": 0.15, "coverage": 0.10}
TEST_RUN_RETENTION_DAYS = 90
SUITE_SNAPSHOT_RETENTION_DAYS = 365


class TestHealthCalculator:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def calculate_all_health_scores(self) -> int:
        stmt = select(TestCase)
        result = await self.db.execute(stmt)
        cases = result.scalars().all()
        count = 0
        for case in cases:
            try:
                runs = await self._get_recent_runs(case.id, days=30)
                if not runs:
                    continue
                scores = await self._calculate_case_scores(case, runs)
                case.health_score = scores["overall"] * 100
                case.health_level = self._score_to_level(scores["overall"] * 100)
                case.pass_rate_7d = scores["pass_rate"]
                case.pass_rate_30d = scores["pass_rate"]
                case.avg_duration_seconds = self._calc_avg_duration(runs)
                case.duration_p90_seconds = self._calc_p90_duration(runs)
                is_flaky, flip_rate, evidence_count = self._detect_flaky(case, runs)
                case.is_flaky = is_flaky
                case.flaky_rate = flip_rate
                case.flaky_evidence_count = evidence_count
                case.flip_count_30d = self._calc_flip_count(runs)
                case.total_runs = len(runs)
                case.total_passed = sum(1 for r in runs if r.result == "passed")
                case.total_failed = sum(1 for r in runs if r.result == "failed")
                case.last_result = runs[-1].result if runs else None
                case.last_run_at = runs[-1].started_at if runs else None
                count += 1
            except Exception as e:
                logger.warning(f"Failed to calculate health for case {case.id}: {e}")
        await self.db.commit()
        return count

    async def _calculate_case_scores(self, case: TestCase, runs: list[TestRun]) -> dict[str, float]:
        pass_rate = self._calc_pass_rate(runs)
        stability = 1.0 - self._calc_flip_rate_by_sha(runs)
        reliability = self._calc_reliability(runs)
        timeliness = await self._calc_timeliness_dynamic(runs, case)
        overall = (
            pass_rate * CASE_WEIGHTS["pass_rate"]
            + stability * CASE_WEIGHTS["stability"]
            + reliability * CASE_WEIGHTS["reliability"]
            + timeliness * CASE_WEIGHTS["timeliness"]
        )
        return {"overall": overall, "pass_rate": pass_rate, "stability": stability, "reliability": reliability, "timeliness": timeliness}

    async def calculate_suite_snapshot(self) -> int:
        stmt = select(TestCase).where(TestCase.test_suite.isnot(None))
        result = await self.db.execute(stmt)
        cases = result.scalars().all()
        suites: dict[str, list[TestCase]] = {}
        for case in cases:
            key = f"{case.test_suite}_{case.hardware or 'unknown'}_{case.card_count or 0}"
            suites.setdefault(key, []).append(case)

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        count = 0
        for key, suite_cases in suites.items():
            parts = key.split("_")
            suite_name = parts[0]
            hardware = parts[1] if len(parts) > 1 else "unknown"
            card_count = int(parts[2]) if len(parts) > 2 else None

            total = len(suite_cases)
            passed = sum(1 for c in suite_cases if c.last_result == "passed")
            failed = sum(1 for c in suite_cases if c.last_result == "failed")
            skipped = sum(1 for c in suite_cases if c.last_result == "skipped")
            flaky = sum(1 for c in suite_cases if c.is_flaky)

            avg_hs = sum(c.health_score or 0 for c in suite_cases) / total if total > 0 else 0
            avg_dur = sum(c.avg_duration_seconds or 0 for c in suite_cases) / total if total > 0 else 0
            p50_dur = self._percentile([c.avg_duration_seconds or 0 for c in suite_cases], 0.5)
            p90_dur = self._percentile([c.avg_duration_seconds or 0 for c in suite_cases], 0.9)
            total_dur = sum(c.avg_duration_seconds or 0 for c in suite_cases)

            cat_counts: dict[str, int] = {}
            for c in suite_cases:
                runs_stmt = select(TestRun.failure_category).where(
                    and_(TestRun.test_case_id == c.id, TestRun.result == "failed")
                ).limit(10)
                runs_result = await self.db.execute(runs_stmt)
                for cat in runs_result.scalars().all():
                    cat_counts[cat or "unknown"] = cat_counts.get(cat or "unknown", 0) + 1

            existing_stmt = select(TestSuiteSnapshot).where(
                and_(
                    TestSuiteSnapshot.suite_name == suite_name,
                    TestSuiteSnapshot.hardware == hardware,
                    TestSuiteSnapshot.snapshot_date == today,
                )
            )
            existing_result = await self.db.execute(existing_stmt)
            existing = existing_result.scalar_one_or_none()

            if existing:
                existing.total_cases = total
                existing.passed_cases = passed
                existing.failed_cases = failed
                existing.skipped_cases = skipped
                existing.flaky_cases = flaky
                existing.pass_rate = passed / total if total > 0 else 0
                existing.health_score = avg_hs
                existing.health_level = self._score_to_level(avg_hs)
                existing.avg_duration_seconds = avg_dur
                existing.duration_p50_seconds = p50_dur
                existing.duration_p90_seconds = p90_dur
                existing.total_duration_seconds = total_dur
                existing.failure_by_category = cat_counts
            else:
                snapshot = TestSuiteSnapshot(
                    suite_name=suite_name, test_type=suite_cases[0].test_type if suite_cases else "unknown",
                    hardware=hardware, card_count=card_count, snapshot_date=today,
                    total_cases=total, passed_cases=passed, failed_cases=failed,
                    skipped_cases=skipped, flaky_cases=flaky,
                    pass_rate=passed / total if total > 0 else 0,
                    health_score=avg_hs, health_level=self._score_to_level(avg_hs),
                    avg_duration_seconds=avg_dur, duration_p50_seconds=p50_dur,
                    duration_p90_seconds=p90_dur, total_duration_seconds=total_dur,
                    failure_by_category=cat_counts,
                )
                self.db.add(snapshot)
            count += 1

        await self.db.commit()
        return count

    async def cleanup_old_test_runs(self) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=TEST_RUN_RETENTION_DAYS)
        result = await self.db.execute(delete(TestRun).where(TestRun.created_at < cutoff))
        snapshot_cutoff = datetime.now(UTC) - timedelta(days=SUITE_SNAPSHOT_RETENTION_DAYS)
        snap_result = await self.db.execute(delete(TestSuiteSnapshot).where(TestSuiteSnapshot.snapshot_date < snapshot_cutoff.strftime("%Y-%m-%d")))
        await self.db.commit()
        return result.rowcount + snap_result.rowcount

    async def _get_recent_runs(self, test_case_id: int, days: int = 30) -> list[TestRun]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        stmt = select(TestRun).where(
            and_(TestRun.test_case_id == test_case_id, TestRun.started_at >= cutoff)
        ).order_by(TestRun.started_at)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    def _calc_pass_rate(self, runs: list[TestRun]) -> float:
        valid = [r for r in runs if r.result in ("passed", "failed")]
        if not valid:
            return 1.0
        return sum(1 for r in valid if r.result == "passed") / len(valid)

    def _calc_flip_rate_by_sha(self, runs: list[TestRun]) -> float:
        by_sha: dict[str, list[str]] = {}
        for r in runs:
            by_sha.setdefault(r.head_sha or "", []).append(r.result)
        flips = 0
        comparable = 0
        for sha, results in by_sha.items():
            if len(results) < 2:
                continue
            for i in range(1, len(results)):
                if results[i] in ("passed", "failed") and results[i-1] in ("passed", "failed"):
                    comparable += 1
                    if results[i] != results[i-1]:
                        flips += 1
        return flips / comparable if comparable > 0 else 0.0

    def _detect_flaky(self, case: TestCase, runs: list[TestRun]) -> tuple[bool, float, int]:
        by_sha: dict[str, list[str]] = {}
        for r in runs:
            by_sha.setdefault(r.head_sha or "", []).append(r.result)
        evidence_count = 0
        for sha, results in by_sha.items():
            if len(results) < 2:
                continue
            has_flip = any(
                results[i] != results[i-1]
                for i in range(1, len(results))
                if results[i] in ("passed", "failed") and results[i-1] in ("passed", "failed")
            )
            if has_flip:
                evidence_count += 1
        flip_rate = self._calc_flip_rate_by_sha(runs)
        sha_count = len([sha for sha, results in by_sha.items() if len(results) >= 2])
        if sha_count < 2:
            is_flaky = False
            flaky_marking = "insufficient_data"
        elif evidence_count >= 2 and flip_rate > 0:
            is_flaky = True
            flaky_marking = "is_flaky"
        elif evidence_count >= 1 and flip_rate > 0:
            is_flaky = False
            flaky_marking = "flaky_candidate"
        else:
            is_flaky = False
            flaky_marking = "stable"
        return is_flaky, flip_rate, evidence_count

    def _calc_flip_count(self, runs: list[TestRun]) -> int:
        by_sha: dict[str, list[str]] = {}
        for r in runs:
            by_sha.setdefault(r.head_sha or "", []).append(r.result)
        count = 0
        for sha, results in by_sha.items():
            for i in range(1, len(results)):
                if results[i] != results[i-1] and results[i] in ("passed", "failed") and results[i-1] in ("passed", "failed"):
                    count += 1
        return count

    def _calc_reliability(self, runs: list[TestRun]) -> float:
        valid = [r for r in runs if r.result in ("passed", "failed")]
        if not valid:
            return 1.0
        passed = sum(1 for r in valid if r.result == "passed")
        return passed / len(valid)

    async def _calc_timeliness_dynamic(self, runs: list[TestRun], case: TestCase) -> float:
        durations = [r.duration_seconds for r in runs if r.duration_seconds is not None]
        if not durations:
            return 1.0
        p90 = sorted(durations)[int(len(durations) * 0.9)] if len(durations) > 1 else durations[0]
        baseline = await self._get_suite_baseline(case)
        if baseline <= 0:
            return 1.0
        return min(1.0, baseline / p90) if p90 > 0 else 1.0

    async def _get_suite_baseline(self, case: TestCase) -> float:
        stmt = select(TestSuiteSnapshot.avg_duration_seconds).where(
            and_(
                TestSuiteSnapshot.suite_name == case.test_suite,
                TestSuiteSnapshot.hardware == (case.hardware or "unknown"),
            )
        ).order_by(desc(TestSuiteSnapshot.snapshot_date)).limit(30)
        result = await self.db.execute(stmt)
        durations = [r[0] for r in result.all() if r[0] is not None]
        if not durations:
            return case.avg_duration_seconds or 600.0
        sorted_d = sorted(durations)
        mid = len(sorted_d) // 2
        p50 = sorted_d[mid] if len(sorted_d) % 2 == 1 else (sorted_d[mid - 1] + sorted_d[mid]) / 2
        if p50 > 0:
            return float(p50)
        return case.avg_duration_seconds or 600.0

    def _calc_avg_duration(self, runs: list[TestRun]) -> float:
        durations = [r.duration_seconds for r in runs if r.duration_seconds is not None]
        return sum(durations) / len(durations) if durations else 0.0

    def _calc_p90_duration(self, runs: list[TestRun]) -> float:
        durations = [r.duration_seconds for r in runs if r.duration_seconds is not None]
        if not durations:
            return 0.0
        return sorted(durations)[int(len(durations) * 0.9)] if len(durations) > 1 else durations[0]

    @staticmethod
    def _score_to_level(score: float) -> str:
        if score >= 90:
            return "A"
        if score >= 75:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    @staticmethod
    def _percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        sorted_vals = sorted(values)
        idx = int(len(sorted_vals) * pct)
        return sorted_vals[min(idx, len(sorted_vals) - 1)]
