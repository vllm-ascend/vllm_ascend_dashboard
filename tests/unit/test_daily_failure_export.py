import csv
import io
from datetime import date, datetime

from api.v1.ci import _serialize_daily_failures_csv
from infrastructure.persistence.models import DailyFailureRecord


def test_daily_failure_csv_contains_tracking_fields_and_utf8_bom():
    record = DailyFailureRecord(
        id=1,
        report_date=date(2026, 8, 21),
        source_branch="main",
        workflow_name="Nightly-A3",
        job_name="single-node (main, model)",
        run_id=123456,
        job_id=654321,
        conclusion="failure",
        started_at=datetime(2026, 8, 21, 1, 2, 3),
        completed_at=datetime(2026, 8, 21, 1, 12, 3),
        duration_seconds=600,
        hardware="A3",
        display_name="模型用例",
        test_model="Model-A",
        model_fo="FO-1",
        owner="张三",
        deployment_type="single-node",
        processing_status="处理中",
        problem_category="基础设施",
        related_pr="123",
        notes="包含,逗号和\n换行",
        github_job_url="https://github.com/example/actions/runs/123/job/654321",
        updated_by="admin",
        status_updated_at=datetime(2026, 8, 21, 2, 0, 0),
    )

    payload = _serialize_daily_failures_csv([record])

    assert payload.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))
    assert len(rows) == 2
    exported = dict(zip(rows[0], rows[1], strict=True))
    assert exported["日期"] == "2026-08-21"
    assert exported["Workflow"] == "Nightly-A3"
    assert exported["运行结果"] == "失败"
    assert exported["责任人"] == "张三"
    assert exported["备注"] == "包含,逗号和\n换行"
    assert exported["开始时间(北京时间)"] == "2026-08-21 09:02:03"
    assert exported["Run ID"] == "123456"
    assert exported["Job ID"] == "654321"


def test_daily_failure_csv_neutralizes_spreadsheet_formulas():
    record = DailyFailureRecord(
        report_date=date(2026, 8, 21),
        source_branch="main",
        workflow_name="Nightly-A3",
        job_name='=HYPERLINK("https://example.com")',
        run_id=1,
        notes="  +SUM(1,1)",
    )

    rows = list(
        csv.reader(
            io.StringIO(_serialize_daily_failures_csv([record]).decode("utf-8-sig"))
        )
    )
    exported = dict(zip(rows[0], rows[1], strict=True))
    assert exported["Job"].startswith("'=")
    assert exported["备注"].startswith("'  +")
