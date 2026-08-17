from collector.ci import CICollector


def test_regular_nightly_dispatch_is_kept() -> None:
    run = {"event": "workflow_dispatch", "display_title": "Nightly-A2"}

    assert CICollector._is_pr_nightly_dispatch(run) is False


def test_pr_nightly_dispatch_marker_is_filtered() -> None:
    run = {"event": "workflow_dispatch"}
    jobs = [
        {
            "name": "single-node (nightly test)",
            "steps": [{"name": "Checkout PR code", "conclusion": "success"}],
        }
    ]

    assert CICollector._is_pr_nightly_dispatch(run, jobs) is True


def test_pr_nightly_dispatch_inputs_are_filtered() -> None:
    run = {
        "event": "workflow_dispatch",
        "inputs": {"vllm_ascend_ref": "abc123", "request_id": "nightly-pr-42"},
    }

    assert CICollector._is_pr_nightly_dispatch(run) is True


def test_non_dispatch_run_is_never_filtered() -> None:
    run = {"event": "schedule"}

    assert CICollector._is_pr_nightly_dispatch(run) is False


def test_skipped_pr_checkout_step_is_normal_nightly() -> None:
    run = {"event": "workflow_dispatch"}
    jobs = [
        {
            "name": "single-node (nightly test)",
            "steps": [{"name": "Checkout PR code", "conclusion": "skipped"}],
        }
    ]

    assert CICollector._is_pr_nightly_dispatch(run, jobs) is False


def test_reusable_pr_only_step_is_filtered() -> None:
    run = {"event": "workflow_dispatch"}
    jobs = [
        {
            "name": "multi-node (nightly test)",
            "steps": [
                {
                    "name": "uninstall vlm vllm-ascend and remove code (if pr test)",
                    "conclusion": "success",
                }
            ]
        }
    ]

    assert CICollector._is_pr_nightly_dispatch(run, jobs) is True


def test_skipped_nightly_build_job_is_not_enough_to_filter() -> None:
    run = {"event": "workflow_dispatch"}
    jobs = [
        {"name": "Build nightly-a3 image", "conclusion": "skipped", "steps": []},
        {
            "name": "single-node (nightly test)",
            "conclusion": "success",
            "steps": [
                {
                    "name": "uninstall vlm vllm-ascend and remove code (if pr test)",
                    "conclusion": "skipped",
                },
                {"name": "Checkout vllm-project/vllm-ascend repo", "conclusion": "skipped"},
            ],
        },
    ]

    assert CICollector._is_pr_nightly_dispatch(run, jobs) is False


def test_pr_marker_in_aggregate_job_is_not_enough_to_filter() -> None:
    run = {"event": "workflow_dispatch"}
    jobs = [
        {
            "name": "Export global env vars as job outputs",
            "conclusion": "success",
            "steps": [{"name": "Checkout PR code", "conclusion": "success"}],
        }
    ]

    assert CICollector._is_pr_nightly_dispatch(run, jobs) is False


def test_accuracy_matrix_job_is_not_enough_to_filter() -> None:
    run = {"event": "workflow_dispatch"}
    jobs = [
        {
            "name": "Generate accuracy test matrix",
            "conclusion": "success",
            "steps": [{"name": "Checkout PR code", "conclusion": "success"}],
        }
    ]

    assert CICollector._is_pr_nightly_dispatch(run, jobs) is False


def test_successful_nightly_build_job_is_not_pr_marker() -> None:
    run = {"event": "workflow_dispatch"}
    jobs = [{"name": "Build nightly-a3 image", "conclusion": "success", "steps": []}]

    assert CICollector._is_pr_nightly_dispatch(run, jobs) is False
