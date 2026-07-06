"""
每日运行报告邮件推送服务
聚合三个时间窗口数据，构建 HTML 邮件并发送

SMTP 配置存储在数据库（ProjectDashboardConfig 表，config_key='smtp_config'）
报告推送配置存储在 config_key='daily_report_config'
与 LLMProviderConfig 设计一致：敏感凭据不放在 .env 文件中
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
from app.core.email import get_smtp_config, send_email
from app.models import CIResult, ModelConfig, ModelReport, PerformanceData, ProjectDashboardConfig, DailyReportHistory
from app.services.daily_data_file_store import DailyDataFileStore

logger = logging.getLogger(__name__)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

REPORT_CONFIG_KEY = "daily_report_config"


class DailyReportService:
    """每日运行报告服务"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.file_store = DailyDataFileStore()

    async def _get_report_config(self) -> dict:
        """从数据库读取报告邮件配置（ProjectDashboardConfig 表）"""
        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == REPORT_CONFIG_KEY
        )
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()

        if config and config.config_value:
            return config.config_value

        return {}

    async def _update_report_config(self, config_value: dict) -> None:
        """更新数据库中的报告邮件配置"""
        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == REPORT_CONFIG_KEY
        )
        result = await self.db.execute(stmt)
        config = result.scalar_one_or_none()

        if config:
            config.config_value = config_value
        else:
            config = ProjectDashboardConfig(
                config_key=REPORT_CONFIG_KEY,
                config_value=config_value,
                description="每日运行报告邮件推送配置（SMTP、收件人等）",
            )
            self.db.add(config)

        await self.db.flush()

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

            if window_key == "yesterday":
                report_data[window_key]["resource"] = await self._collect_resource_data()
                report_data[window_key]["test"] = await self._collect_test_data()

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

        model_ids_in_window = {r.model_config_id for r in reports}

        earlier_stmt = select(ModelReport).where(ModelReport.created_at < start_dt)
        earlier_result = await self.db.execute(earlier_stmt)
        earlier_ids = {r.model_config_id for r in earlier_result.scalars().all()}

        new_model_ids = model_ids_in_window - earlier_ids
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
        """采集性能指标概况（从 ModelReport.metrics_json 提取，PerformanceData 表暂无采集器）"""
        stmt = select(ModelReport).where(
            ModelReport.created_at >= start_dt,
            ModelReport.created_at <= end_dt,
        )
        result = await self.db.execute(stmt)
        reports = result.scalars().all()

        if not reports:
            return {"avg_throughput": None, "avg_p50_latency": None, "avg_p99_latency": None}

        throughputs = []
        p50_latencies = []
        p99_latencies = []

        for r in reports:
            try:
                metrics = json.loads(r.metrics_json) if isinstance(r.metrics_json, str) else r.metrics_json
                if not metrics or not isinstance(metrics, dict):
                    continue
                for key in ["throughput", "avg_throughput", "overall_throughput"]:
                    if key in metrics:
                        throughputs.append(float(metrics[key]))
                        break
                for key in ["p50_latency", "avg_p50_latency", "first_token_latency", "avg_first_token_latency", "ttft"]:
                    if key in metrics:
                        p50_latencies.append(float(metrics[key]))
                        break
                for key in ["p99_latency", "avg_p99_latency"]:
                    if key in metrics:
                        p99_latencies.append(float(metrics[key]))
                        break
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

        return {
            "avg_throughput": sum(throughputs) / len(throughputs) if throughputs else None,
            "avg_p50_latency": sum(p50_latencies) / len(p50_latencies) if p50_latencies else None,
            "avg_p99_latency": sum(p99_latencies) / len(p99_latencies) if p99_latencies else None,
        }

    async def _collect_resource_data(self) -> dict:
        """采集资源看板 NPU 利用率概况"""
        try:
            from app.services.resource_metrics import ResourceMetricsService
            svc = ResourceMetricsService(self.db)
            data = await svc.query_npu_metrics(time_range="24h")
            clusters = []
            for c in data.get("clusters", []):
                metrics = c.get("metrics", [])
                if not metrics:
                    continue
                avg_util = sum(m.get("npu_utilization", 0) for m in metrics) / len(metrics)
                last = metrics[-1]
                clusters.append({
                    "cluster_name": c.get("cluster_name", ""),
                    "avg_npu_utilization": round(avg_util, 1),
                    "npu_total": last.get("npu_total", 0),
                    "npu_used": last.get("npu_used", 0),
                    "executing_pods": last.get("executing_pods_count", 0),
                })
            return {"clusters": clusters}
        except Exception as e:
            logger.warning(f"Failed to collect resource data: {e}")
            return {"clusters": []}

    async def _collect_test_data(self) -> dict:
        """采集测试看板概况"""
        try:
            from app.services.test_board_service import TestBoardService
            svc = TestBoardService(self.db)
            overview = await svc.get_overview(days=1)
            return {
                "health_score": overview.get("health_score", {}),
                "total_cases": overview.get("total_cases", 0),
                "pass_rate_7d": overview.get("pass_rate_7d", 0),
                "flaky_case_count": overview.get("flaky_case_count", 0),
            }
        except Exception as e:
            logger.warning(f"Failed to collect test data: {e}")
            return {}

    def build_email_html(self, report_data: dict) -> str:
        """使用 Jinja2 渲染 HTML 邮件（旧模板，降级时使用）"""
        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
        template = env.get_template("daily_report.html")

        dashboard_url = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "http://localhost:3000"

        return template.render(
            report_data=report_data,
            report_date=report_data["report_date"],
            dashboard_url=dashboard_url,
        )

    def build_ai_email_html(self, ai_report_markdown: str, report_date: str) -> str:
        """使用 Jinja2 渲染 LLM 报告 HTML 邮件（新模板）"""
        import markdown as md_lib
        ai_report_html = md_lib.markdown(ai_report_markdown, extensions=['tables', 'fenced_code'])

        env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
        template = env.get_template("ai_report_email.html")

        dashboard_url = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "http://localhost:3000"

        return template.render(
            report_date=report_date,
            ai_report_html=ai_report_html,
            dashboard_url=dashboard_url,
        )

    async def _generate_ai_report(self, report_data: dict) -> str | None:
        """用 LLM 生成洞察式每日报告（替换 300 字截断片段）

        读取 daily-report-writer 技能作为 system prompt，
        将全量看板数据作为 user prompt 传给 LLM。
        """
        try:
            from app.models.daily_summary import LLMProviderConfig
            from app.services.llm_client import LLMClient
            from app.services.skill_registry import get_skill_registry

            # 获取 LLM 配置
            llm_config = (await self.db.execute(
                select(LLMProviderConfig).where(LLMProviderConfig.is_active == True).limit(1)
            )).scalar_one_or_none()
            if not llm_config:
                logger.warning("No active LLM provider configured, skipping AI report generation")
                return None

            # 获取 system prompt（从 skill_registry 读取 SKILL.md）
            registry = get_skill_registry()
            skill = registry.get_skill_by_scope("daily_report")
            system_prompt = skill.content if skill and skill.content else (
                "你是一名 vLLM Ascend 社区运营分析师。请根据提供的全量看板数据，"
                "生成结构化每日运行报告。报告应包含：一句话总结、整体健康度、"
                "Nightly 流水线概况、PR 流水线概况、项目动态、风险与待办。"
                "每段先结论后数据，空数据板块整段省略。"
            )

            # 构造 user prompt（全量数据 JSON）
            user_prompt = (
                f"请根据以下全量看板数据生成 {report_data.get('report_date', '昨日')} 的每日运行报告。\n\n"
                f"以下是各时间窗口的聚合数据（JSON 格式）：\n\n"
                f"```json\n{json.dumps(report_data, ensure_ascii=False, default=str)[:8000]}\n```\n\n"
                f"请严格按照系统提示词的板块结构输出 Markdown 格式的报告。"
            )

            client = LLMClient()
            result = await client.generate(
                provider=llm_config.provider,
                model=llm_config.default_model,
                api_key=llm_config.api_key,
                api_base=llm_config.api_base_url,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
            )

            logger.info(f"AI report generated: tokens={result.prompt_tokens + result.completion_tokens}")
            return result.content

        except Exception as e:
            logger.error(f"AI report generation failed: {e}", exc_info=True)
            return None

    async def send_report(self, report_date: date) -> DailyReportHistory:
        """
        生成报告并发送邮件，记录发送历史

        SMTP 配置从数据库读取，不从 .env 文件读取

        Args:
            report_date: 报告日期（昨日日期）

        Returns:
            DailyReportHistory 记录
        """
        report_config = await self._get_report_config()
        smtp_config = await get_smtp_config(self.db)

        smtp_host = smtp_config.get("smtp_host", "")
        smtp_port = int(smtp_config.get("smtp_port", 587))
        smtp_username = smtp_config.get("smtp_username", "")
        smtp_password = smtp_config.get("smtp_password", "")
        smtp_use_tls = bool(smtp_config.get("smtp_use_tls", True))
        from_email = smtp_config.get("from_email", "")
        recipients_str = report_config.get("report_recipients", "")
        cc_str = report_config.get("report_cc_recipients", "")

        recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
        cc_recipients = [r.strip() for r in cc_str.split(",") if r.strip()]

        subject_template = report_config.get("report_subject_template", settings.REPORT_SUBJECT_TEMPLATE)
        subject = subject_template.format(date=report_date.isoformat())

        history = DailyReportHistory(
            report_date=report_date.isoformat(),
            recipients=recipients_str,
            subject=subject,
            status="pending",
        )
        self.db.add(history)
        await self.db.flush()

        try:
            report_data = await self.generate_report(report_date)

            # 用 LLM 生成洞察式报告
            ai_report = await self._generate_ai_report(report_data)
            if ai_report:
                # LLM 报告直接作为邮件正文（新模板），替代旧模板
                history.ai_report_content = ai_report
                # 同时保留 ai_summary_snippet 供前端兼容
                report_data["yesterday"]["github"]["ai_summary_snippet"] = ai_report
                try:
                    html_content = self.build_ai_email_html(ai_report, report_data["report_date"])
                    logger.info("AI report generated, used as email body with new template")
                except Exception as e:
                    logger.warning(f"Failed to build AI email HTML, falling back to old template: {e}")
                    html_content = self.build_email_html(report_data)
            else:
                # 降级到旧模板
                html_content = self.build_email_html(report_data)
                logger.info("AI report generation skipped or failed, using original template")

            history.ci_summary = report_data["yesterday"]["ci"]
            history.model_summary = report_data["yesterday"]["model"]
            history.github_summary = report_data["yesterday"]["github"]
            history.performance_summary = report_data["yesterday"]["performance"]

            if not recipients:
                history.status = "failed"
                history.error_message = "No recipients configured"
                await self.db.commit()
                return history

            if not smtp_host:
                history.status = "failed"
                history.error_message = "SMTP_HOST not configured"
                await self.db.commit()
                return history

            result = await send_email(
                subject=subject,
                html_content=html_content,
                recipients=recipients,
                cc_recipients=cc_recipients,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_username=smtp_username,
                smtp_password=smtp_password,
                smtp_use_tls=smtp_use_tls,
                from_email=from_email,
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


def _today_shanghai():
    """获取当前上海日期（date 对象），不受服务器系统时区影响"""
    from datetime import datetime
    return datetime.now(SHANGHAI_TZ).date()


def _now_shanghai():
    """获取当前上海时间"""
    from datetime import datetime
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)