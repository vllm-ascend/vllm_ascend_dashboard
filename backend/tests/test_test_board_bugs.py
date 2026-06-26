"""Tests for test board bug fixes (Issue #81): B1, B2, B3, D3, D4."""
from datetime import UTC, datetime, timedelta

import pytest

from app.services.test_board_service import TestBoardService
from app.services.test_health_calculator import TestHealthCalculator
from tests.conftest import make_test_case, make_test_run

# ============================================================================
# B1: calculate_all_health_scores must be awaited — health scores populated
# ============================================================================

class TestB1HealthScoresPopulated:
    """B1: await calc.calculate_all_health_scores() must actually execute."""

    @pytest.mark.asyncio
    async def test_health_scores_populated_after_calculation(self, db_session):
        """After calculate_all_health_scores, TestCase fields must be non-null."""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_b1", pass_rate_7d=None, health_score=None)
        db_session.add(case)
        await db_session.flush()

        for i in range(5):
            db_session.add(make_test_run(
                test_case_id=case.id,
                result="passed" if i < 4 else "failed",
                duration_seconds=100.0,
                head_sha=f"sha{i}",
                started_at=now - timedelta(days=i),
            ))
        await db_session.commit()

        calc = TestHealthCalculator(db_session)
        count = await calc.calculate_all_health_scores()

        assert count == 1, "Should have calculated health for 1 case"
        assert case.health_score is not None, "health_score must be populated"
        assert case.health_score > 0, "health_score must be > 0 for 4/5 pass rate"
        assert case.pass_rate_7d is not None, "pass_rate_7d must be populated"
        assert case.total_runs == 5, "total_runs must be 5"
        assert case.total_passed == 4, "total_passed must be 4"
        assert case.total_failed == 1, "total_failed must be 1"
        assert case.avg_duration_seconds is not None, "avg_duration_seconds must be populated"
        assert case.last_result is not None, "last_result must be populated"

    @pytest.mark.asyncio
    async def test_health_level_assigned(self, db_session):
        """Health level (A/B/C/D) must be assigned after calculation."""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_b1_level")
        db_session.add(case)
        await db_session.flush()

        for i in range(10):
            db_session.add(make_test_run(
                test_case_id=case.id,
                result="passed",
                duration_seconds=50.0,
                head_sha=f"sha{i}",
                started_at=now - timedelta(days=i),
            ))
        await db_session.commit()

        calc = TestHealthCalculator(db_session)
        await calc.calculate_all_health_scores()

        assert case.health_level is not None
        assert case.health_level in ("A", "B", "C", "D")
        assert case.health_level == "A", "10/10 passes should be A level"

    @pytest.mark.asyncio
    async def test_flaky_detection_works(self, db_session):
        """is_flaky must be detectable after health calculation."""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_b1_flaky")
        db_session.add(case)
        await db_session.flush()

        results = ["passed", "failed", "passed", "failed", "passed", "failed"]
        for i, result in enumerate(results):
            db_session.add(make_test_run(
                test_case_id=case.id,
                result=result,
                duration_seconds=60.0,
                head_sha=f"sha{i // 2}",
                started_at=now - timedelta(days=i),
            ))
        await db_session.commit()

        calc = TestHealthCalculator(db_session)
        await calc.calculate_all_health_scores()

        assert case.is_flaky is not None
        assert case.flaky_rate is not None
        assert case.flaky_rate > 0, "Flaky rate should be > 0 for alternating results"


# ============================================================================
# B2: _calculate_case_scores must be async — timeliness is a float not coroutine
# ============================================================================

class TestB2AsyncSyncFix:
    """B2: _calculate_case_scores is async, timeliness is a real float."""

    @pytest.mark.asyncio
    async def test_calculate_case_scores_returns_floats(self, db_session):
        """_calculate_case_scores must return real floats, not coroutines."""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_b2", avg_duration_seconds=100.0)
        db_session.add(case)
        await db_session.flush()

        runs = []
        for i in range(5):
            runs.append(make_test_run(
                test_case_id=case.id,
                result="passed",
                duration_seconds=80.0 + i * 10,
                head_sha=f"sha{i}",
                started_at=now - timedelta(days=i),
            ))
            db_session.add(runs[-1])
        await db_session.commit()

        calc = TestHealthCalculator(db_session)
        scores = await calc._calculate_case_scores(case, runs)

        assert isinstance(scores, dict)
        assert isinstance(scores["overall"], float), "overall must be float, not coroutine"
        assert isinstance(scores["timeliness"], float), "timeliness must be float, not coroutine"
        assert isinstance(scores["pass_rate"], float)
        assert isinstance(scores["stability"], float)
        assert isinstance(scores["reliability"], float)
        assert 0 <= scores["overall"] <= 1.0

    @pytest.mark.asyncio
    async def test_timeliness_not_coroutine(self, db_session):
        """Specifically verify timeliness is a float (the B2 bug returned a coroutine)."""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_b2_timeliness", avg_duration_seconds=100.0)
        db_session.add(case)
        await db_session.flush()

        runs = []
        for i in range(3):
            runs.append(make_test_run(
                test_case_id=case.id,
                result="passed",
                duration_seconds=120.0,
                head_sha=f"sha{i}",
                started_at=now - timedelta(days=i),
            ))
            db_session.add(runs[-1])
        await db_session.commit()

        calc = TestHealthCalculator(db_session)
        scores = await calc._calculate_case_scores(case, runs)

        import asyncio
        assert not asyncio.iscoroutine(scores["timeliness"]), (
            "timeliness must not be a coroutine — B2 bug caused TypeError"
        )
        assert 0 <= scores["timeliness"] <= 1.0

    @pytest.mark.asyncio
    async def test_no_type_error_on_calculation(self, db_session):
        """Full calculate_all_health_scores must not skip cases due to TypeError."""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_b2_no_error")
        db_session.add(case)
        await db_session.flush()

        for i in range(5):
            db_session.add(make_test_run(
                test_case_id=case.id,
                result="passed",
                duration_seconds=100.0,
                head_sha=f"sha{i}",
                started_at=now - timedelta(days=i),
            ))
        await db_session.commit()

        calc = TestHealthCalculator(db_session)
        count = await calc.calculate_all_health_scores()

        assert count == 1, (
            "Case must not be skipped due to TypeError (B2 bug caused all cases to fail)"
        )
        assert case.health_score is not None


# ============================================================================
# B3: Overview health dimensions must be real, not hardcoded
# ============================================================================

class TestB3RealHealthDimensions:
    """B3: stability/reliability/timeliness/coverage must be computed from data."""

    @pytest.mark.asyncio
    async def test_dimensions_not_hardcoded(self, db_session):
        """Overview dimensions must NOT be the old hardcoded values."""
        hardcoded_values = {"stability": 0.85, "reliability": 0.88, "timeliness": 0.78, "coverage": 0.71}

        for i in range(10):
            db_session.add(make_test_case(
                test_name=f"test_b3_{i}",
                flaky_rate=0.2,
                pass_rate_7d=0.6,
                avg_duration_seconds=100.0,
                owner="dev1",
                health_score=70.0,
                health_level="C",
            ))
        await db_session.commit()

        service = TestBoardService(db_session)
        result = await service.get_overview(days=7)

        hs = result["health_score"]
        for dim, old_val in hardcoded_values.items():
            assert hs[dim] != old_val, (
                f"{dim}={hs[dim]} must not be hardcoded {old_val}"
            )

    @pytest.mark.asyncio
    async def test_stability_reflects_flaky_rate(self, db_session):
        """stability = 1 - avg(flaky_rate)."""
        for i in range(5):
            db_session.add(make_test_case(
                test_name=f"test_b3_stab_{i}",
                flaky_rate=0.3,
                pass_rate_7d=0.8,
                health_score=75.0,
                health_level="B",
            ))
        await db_session.commit()

        service = TestBoardService(db_session)
        result = await service.get_overview(days=7)

        expected_stability = round(1.0 - 0.3, 2)
        assert result["health_score"]["stability"] == expected_stability

    @pytest.mark.asyncio
    async def test_coverage_reflects_ownership(self, db_session):
        """coverage = cases_with_owner / total_cases."""
        for i in range(4):
            db_session.add(make_test_case(
                test_name=f"test_b3_cov_{i}",
                owner="dev1" if i < 2 else None,
                pass_rate_7d=0.8,
                health_score=75.0,
                health_level="B",
            ))
        await db_session.commit()

        service = TestBoardService(db_session)
        result = await service.get_overview(days=7)

        assert result["health_score"]["coverage"] == 0.5, "2 of 4 cases have owner"

    @pytest.mark.asyncio
    async def test_timeliness_reflects_duration_data(self, db_session):
        """timeliness = cases_with_duration / total_cases."""
        for i in range(4):
            db_session.add(make_test_case(
                test_name=f"test_b3_time_{i}",
                avg_duration_seconds=100.0 if i < 3 else None,
                pass_rate_7d=0.8,
                health_score=75.0,
                health_level="B",
            ))
        await db_session.commit()

        service = TestBoardService(db_session)
        result = await service.get_overview(days=7)

        assert result["health_score"]["timeliness"] == 0.75, "3 of 4 cases have duration"

    @pytest.mark.asyncio
    async def test_reliability_reflects_pass_rate(self, db_session):
        """reliability = avg(pass_rate_7d)."""
        db_session.add(make_test_case(
            test_name="test_b3_rel_1", pass_rate_7d=0.8, health_score=75.0, health_level="B",
        ))
        db_session.add(make_test_case(
            test_name="test_b3_rel_2", pass_rate_7d=0.6, health_score=60.0, health_level="C",
        ))
        await db_session.commit()

        service = TestBoardService(db_session)
        result = await service.get_overview(days=7)

        expected = round((0.8 + 0.6) / 2, 2)
        assert result["health_score"]["reliability"] == expected


# ============================================================================
# D3: noise_ratio = (Flaky + infrastructure) / total_failures
# ============================================================================

class TestD3NoiseRatioFormula:
    """D3: noise_ratio must use (Flaky + infra) / total, not (infra + tb + unk) / total."""

    @pytest.mark.asyncio
    async def test_noise_ratio_includes_flaky(self, db_session):
        """noise_ratio must include flaky failures, not test_bug/unknown."""
        now = datetime.now(UTC)
        case_flaky = make_test_case(
            test_name="test_d3_flaky", is_flaky=True, last_result="failed",
            flaky_rate=0.3,
        )
        case_normal = make_test_case(
            test_name="test_d3_normal", is_flaky=False, last_result="failed",
            flaky_rate=0.0,
        )
        db_session.add_all([case_flaky, case_normal])
        await db_session.flush()

        db_session.add(make_test_run(
            test_case_id=case_flaky.id, result="failed",
            failure_category="product_bug", started_at=now - timedelta(days=1),
        ))
        db_session.add(make_test_run(
            test_case_id=case_normal.id, result="failed",
            failure_category="infrastructure", started_at=now - timedelta(days=1),
        ))
        await db_session.commit()

        service = TestBoardService(db_session)
        result = await service.get_failure_breakdown(days=30)

        total = result["total"]
        infra = result["infrastructure"]
        flaky_failures = 1

        expected = round((flaky_failures + infra) / total, 2)
        assert result["noise_ratio"] == expected, (
            f"noise_ratio should be (flaky={flaky_failures} + infra={infra}) / total={total} = {expected}, "
            f"got {result['noise_ratio']}"
        )

    @pytest.mark.asyncio
    async def test_noise_ratio_excludes_test_bug_and_unknown(self, db_session):
        """Old formula included test_bug + unknown; new formula must not."""
        now = datetime.now(UTC)
        case = make_test_case(test_name="test_d3_excl", is_flaky=False, last_result="failed")
        db_session.add(case)
        await db_session.flush()

        db_session.add(make_test_run(
            test_case_id=case.id, result="failed",
            failure_category="test_bug", started_at=now - timedelta(days=1),
        ))
        db_session.add(make_test_run(
            test_case_id=case.id, result="failed",
            failure_category="unknown", started_at=now - timedelta(days=1),
        ))
        await db_session.commit()

        service = TestBoardService(db_session)
        result = await service.get_failure_breakdown(days=30)

        assert result["total"] == 2
        assert result["noise_ratio"] == 0.0, (
            "No flaky failures and no infra → noise_ratio should be 0, "
            "old formula would give (0+1+1)/2=1.0"
        )


# ============================================================================
# D4: suite_distribution keys must not have redundant hardware
# ============================================================================

class TestD4SuiteDistributionKey:
    """D4: suite_distribution key must not duplicate hardware in suite name."""

    @pytest.mark.asyncio
    async def test_no_redundant_hardware_in_key(self, db_session):
        """When suite name already contains hardware, key must not append it again."""
        db_session.add(make_test_case(
            test_name="test_d4_1", test_suite="Nightly-A2", hardware="A2",
        ))
        db_session.add(make_test_case(
            test_name="test_d4_2", test_suite="Nightly-A2", hardware="A2",
        ))
        await db_session.commit()

        service = TestBoardService(db_session)
        result = await service.get_overview(days=7)

        keys = list(result["suite_distribution"].keys())
        assert "Nightly-A2" in keys, f"Key should be 'Nightly-A2', got {keys}"
        assert "Nightly-A2-A2" not in keys, "Redundant key 'Nightly-A2-A2' must not exist"
        assert result["suite_distribution"]["Nightly-A2"] == 2

    @pytest.mark.asyncio
    async def test_hardware_appended_when_not_in_suite_name(self, db_session):
        """When suite name doesn't contain hardware, key should include it."""
        db_session.add(make_test_case(
            test_name="test_d4_3", test_suite="Nightly", hardware="A3",
        ))
        await db_session.commit()

        service = TestBoardService(db_session)
        result = await service.get_overview(days=7)

        keys = list(result["suite_distribution"].keys())
        assert "Nightly-A3" in keys, f"Key should be 'Nightly-A3', got {keys}"
