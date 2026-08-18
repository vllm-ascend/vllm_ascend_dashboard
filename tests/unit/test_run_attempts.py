from infrastructure.persistence.run_attempts import (
    extract_run_attempt,
    filter_current_run_attempt,
    is_current_run_attempt,
)


def test_extract_run_attempt_accepts_stored_json():
    assert extract_run_attempt('{"run_attempt": 2}') == 2
    assert extract_run_attempt('{"run_attempt": "3"}') == 3
    assert extract_run_attempt("not-json") is None


def test_unknown_attempt_is_kept_for_legacy_rows():
    assert is_current_run_attempt('{"run_attempt": 1}', 2) is False
    assert is_current_run_attempt('{"run_attempt": 2}', 2) is True
    assert is_current_run_attempt('{"job_id": 123}', 2) is True
    assert is_current_run_attempt('{"run_attempt": 1}', None) is True


def test_filter_current_attempt_removes_superseded_jobs():
    jobs = [
        {"data": '{"run_attempt": 1}', "name": "old"},
        {"data": '{"run_attempt": 2}', "name": "current"},
        {"data": '{"run_attempt": 2}', "name": "current-2"},
    ]
    assert [job["name"] for job in filter_current_run_attempt(jobs, 2)] == [
        "current",
        "current-2",
    ]


def test_filter_falls_back_when_attempt_is_not_persisted():
    jobs = [{"data": "{}", "name": "legacy"}]
    assert filter_current_run_attempt(jobs, 2) == jobs
