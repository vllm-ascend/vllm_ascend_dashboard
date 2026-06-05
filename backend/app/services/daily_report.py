"""
每日运行报告邮件推送服务
聚合三个时间窗口数据，构建 HTML 邮件并发送
"""
import json
import logging
from datetime import date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.email import send_email
from app.models import CIResult, CIJob, ModelConfig, ModelReport, PerformanceData, DailyReportHistory
from app.services.daily_data_file_store import DailyDataFileStore

logger = logging.getLogger(__name__)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


class DailyReportService:
    """每日运行报告服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.file_store = DailyDataFileStore()

    async def generate_report(self, report_date: date) -> dict:
        """
        生成完整报告数据（三个时间窗口）

        Args:
            report_date: 报告日期（昨日日期）

        Returns:
            报告数据字典，包含 yesterday/last_week/last_month 三个窗口
        """
        yesterday_start = report_date
        yesterday_end = report_date
        last_week_start = report_date - timedelta(days=6)
        last_month_start = report_date - timedelta(days=29)

        windows = {
            "yesterday": (yesterday_start, yesterday_end),
            "last_week": (last_week_start, yesterday_end),
            "last_month": (last_month_start, yesterday_end),
        }

        report_data = {}
        for window_key, (start, end) in windows.items():
            start_dt = _date_to_utc_start(start)
            end_dt = _date_to_utc_end(end)

            ci_data = await self._collect_ci_data(start_dt, end_dt)
            model_data = await self._collect_model_data(start_dt, end_dt)
            gh_data = await self._collect_github_data(start, end, window_key)
            perf_data = await self._collect_perf_data(start_dt, end_dt)

            report_data[window_key] = {
                "ci": ci_data,
                "model": model_data,
                "github": gh_data,
                "performance": perf_data,
            }

        return {"report_date": report_date.isoformat(), **report_data}

    async def _collect_ci_data(self, start_dt, end_dt) -> dict:
        """采集 CI 运行概况"""
        stmt = select(CIResult).where(
            CIResult.started_at >= start_dt,
            CIResult.started_at <= end_dt,
            CIResult.status == "completed",
        )
        result = await self.db.execute(stmt)
        runs = result.scalars().all()

        total = len(runs)
        success = sum(1 for r in runs if r.conclusion == "success")
        failure = sum(1 for r in runs if r.conclusion == "failure")
        rate = (success / total * 100) if total > 0 else 0.0
        avg_dur = (
            sum(r.duration_seconds or 0 for r in runs) / total if total > 0 else None
        )

        failed_wfs = []
        for r in runs:
            if r.conclusion == "failure":
                failed_wfs.append({
                    "workflow_name": r.workflow_name,
                    "run_number": r.run_number,
                    "duration_seconds": r.duration_seconds or 0,
                    "hardware": r.hardware,
                })

        return {
            "total_runs": total,
            "success_runs": success,
            "failure_runs": failure,
            "success_rate": rate,
            "avg_duration_seconds": avg_dur,
            "failed_workflows": failed_wfs,
        }

    async def _collect_model_data(self, start_dt, end_dt) -> dict:
        """采集模型验证概况"""
        stmt = select(ModelReport).where(
            ModelReport.created_at >= start_dt,
            ModelReport.created_at <= end_dt,
        )
        result = await self.db.execute(stmt)
        reports = result.scalars().all()

        total = len(reports)
        pass_count = sum(1 for r in reports if r.pass_fail == "pass")
        fail_count = sum(1 for r in reports if r.pass_fail == "fail")
        rate = (pass_count / total * 100) if total > 0 else 0.0

        model_names_in_window = {r.model_config_id for r in reports}

        earlier_stmt = select(ModelReport).where(ModelReport.created_at < start_dt)
        earlier_result = await self.db.execute(earlier_stmt)
        earlier_ids = {r.model_config_id for r in earlier_result.scalars().all()}

        new_model_ids = model_names_in_window - earlier_ids
        new_models = []
        if new_model_ids:
            mc_stmt = select(ModelConfig).where(ModelConfig.id.in_(new_model_ids))
            mc_result = await self.db.execute(mc_stmt)
            new_models = [mc.model_name for mc in mc_result.scalars().all()]

        failed_models = []
        for r in reports:
            if r.pass_fail == "fail":
                mc_stmt2 = select(ModelConfig).where(ModelConfig.id == r.model_config_id)
                mc2 = (await self.db.execute(mc_stmt2)).scalar_one_or_none()
                failed_models.append({
                    "model_name": mc2.model_name if mc2 else f"ID:{r.model_config_id}",
                    "hardware": r.hardware,
                    "vllm_version": r.vllm_version,
                })

        return {
            "total_reports": total,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "pass_rate": rate,
            "new_models": new_models,
            "failed_models": failed_models,
        }

    async def _collect_github_data(self, start: date, end: date, window_key: str) -> dict:
        """采集 GitHub 活动概况"""
        project = "ascend"
        pr_count = 0
        issue_count = 0
        commit_count = 0
        ai_snippet = None

        current_date = end
        while current_date >= start:
            data = await self.file_store.load_daily_data(project, current_date)
            if data:
                counts = data.get("counts", {})
                pr_count += counts.get("prs", len(data.get("pull_requests", [])))
                issue_count += counts.get("issues", len(data.get("issues", [])))
                commit_count += counts.get("commits", len(data.get("commits", [])))
            current_date -= timedelta(days=1)

        if window_key == "yesterday":
            summary = await self.file_store.load_summary(project, start)
            if summary and summary.get("summary_markdown"):
                md = summary["summary_markdown"]
                lines = md.split("\n")
                snippet_lines = [l for l in lines[:8] if l.strip()]
                ai_snippet = " ".join(snippet_lines)[:300]

        return {
            "pr_count": pr_count,
            "issue_count": issue_count,
            "commit_count": commit_count,
            "ai_summary_snippet": ai_snippet,
        }

    async def _collect_perf_data(self, start_dt, end_dt) -> dict:
        """采集性能指标概况"""
        stmt = select(PerformanceData).where(
            PerformanceData.timestamp >= start_dt,
            PerformanceData.timestamp <= end_dt,
        )
        result = await self.db.execute(stmt)
        perf_records = result.scalars().all()

        if not perf_records:
            return {"avg_throughput": None, "avg_p50_latency": None, "avg_p99_latency": None}

        throughputs = []
        p50_latencies = []
        p99_latencies = []

        for p in perf_records:
            try:
                metrics = json.loads(p.metrics_json) if isinstance(p.metrics_json, str) else p.metrics_json
                if metrics:
                    if "throughput" in metrics:
                        throughputs.append(float(metrics["throughput"]))
                    if "p50_latency" in metrics:
                        p50_latencies.append(float(metrics["p50_latency"]))
                    if "p99_latency" in metrics:
                        p99_latencies.append(float(metrics["p99_latency"]))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        avg_throughput = sum(throughputs) / len(throughputs) if throughputs else None
        avg_p50 = sum(p50_latencies) / len(p50_latencies) if p50_latencies else None
        avg_p99 = sum(p99_latencies) / len(p99_latencies) if p99_latencies else None

        return {
            "avg_throughput": avg_throughput,
            "avg_p50_latency": avg_p50,
            "avg_p99_latency": avg_p99,
        }

    def build_email_html(self, report_data: dict) -> str:
        """使用 Jinja2 渲染 HTML 邶件"""
        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
        template = env.get_template("daily_report.html")

        dashboard_url = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "http://localhost:3000"

        return template.render(
            report_data=report_data,
            report_date=report_data["report_date"],
            dashboard_url=dashboard_url,
        )

    async def send_report(self, report_date: date) -> DailyReportHistory:
        """
        生成报告并发送邮件，记录发送历史

        Args:
            report_date: 报告日期（昨日日期）

        Returns:
            DailyReportHistory 记录
        """
        recipients = [r.strip() for r in settings.REPORT_RECIPIENTS.split(",") if r.strip()] if settings.REPORT_RECIPIENTS else []
        cc_recipients = [r.strip() for r in settings.REPORT_CC_RECIPIENTS.split(",") if r.strip()] if settings.REPORT_CC_RECIPIENTS else []

        subject = settings.REPORT_SUBJECT_TEMPLATE.format(date=report_date.isoformat())

        history = DailyReportHistory(
            report_date=report_date.isoformat(),
            recipients=settings.REPORT_RECIPIENTS,
            subject=subject,
            status="pending",
        )
        self.db.add(history)
        await self.db.flush()

        try:
            report_data = await self.generate_report(report_date)

            html_content = self.build_email_html(report_data)

            history.ci_summary = report_data["yesterday"]["ci"]
            history.model_summary = report_data["yesterday"]["model"]
            history.github_summary = report_data["yesterday"]["github"]
            history.performance_summary = report_data["yesterday"]["performance"]

            if not recipients:
                history.status = "failed"
                history.error_message = "No recipients configured"
                await self.db.commit()
                return history

            result = await send_email(
                subject=subject,
                html_content=html_content,
                recipients=recipients,
                cc_recipients=cc_recipients,
            )

            if result["success"]:
                history.status = "sent"
                history.sent_at = _now_shanghai()
            else:
                history.status = "failed"
                history.error_message = result.get("error", "Unknown error")

            await self.db.commit()
            return history

        except Exception as e:
            history.status = "failed"
            history.error_message = str(e)
            await self.db.commit()
            logger.error(f"Failed to send daily report: {e}", exc_info=True)
            return history

    async def get_report_history(self, limit: int = 20, offset: int = 0) -> tuple[list[DailyReportHistory], int]:
        """查询报告发送历史"""
        count_stmt = select(func.count(DailyReportHistory.id))
        total = (await self.db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(DailyReportHistory)
            .order_by(DailyReportHistory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_latest_report(self) -> DailyReportHistory | None:
        """获取最近一次报告记录"""
        stmt = select(DailyReportHistory).order_by(DailyReportHistory.created_at.desc()).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()


def _date_to_utc_start(d: date):
    """将北京时间日期转为 UTC 范围起始"""
    from datetime import datetime, time
    start = datetime.combine(d, time.min, tzinfo=SHANGHAI_TZ)
    return start.astimezone(timezone.utc)


def _date_to_utc_end(d: date):
    """将北京时间日期转为 UTC 范围结束"""
    from datetime import datetime, time
    end = datetime.combine(d, time.max, tzinfo=SHANGHAI_TZ)
    return end.astimezone(timezone.utc)


def _now_shanghai():
    """获取当前上海时间"""
    from datetime import datetime
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)