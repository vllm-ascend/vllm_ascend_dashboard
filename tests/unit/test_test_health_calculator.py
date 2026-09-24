from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tooling.analytics.test_health_calculator import TestHealthCalculator


class _Result:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def all(self):
        return self._value

    def scalar_one_or_none(self):
        return None


@pytest.mark.asyncio
async def test_suite_snapshot_keeps_underscore_filename_as_suite_name():
    case = SimpleNamespace(
        id=1,
        test_suite="schedule_nightly_test_a3.yaml",
        hardware="A3",
        card_count=0,
        last_result="failed",
        is_flaky=False,
        health_score=0,
        avg_duration_seconds=0,
        test_type="nightly",
    )
    db = AsyncMock()
    db.execute.side_effect = [
        _Result([case]),
        _Result([]),
        _Result(None),
    ]
    db.add = Mock()
    db.commit = AsyncMock()

    count = await TestHealthCalculator(db).calculate_suite_snapshot()

    assert count == 1
    snapshot = db.add.call_args.args[0]
    assert snapshot.suite_name == "schedule_nightly_test_a3.yaml"
    assert snapshot.hardware == "A3"
    assert snapshot.card_count == 0
