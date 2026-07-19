import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Optional

from sqlalchemy import select, delete, and_, func, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CIJob, CIResult, ProjectDashboardConfig, JobFailureAnalysis
from app.models.daily_summary import LLMProviderConfig
from app.services.failure_analysis_file_store import FailureAnalysisFileStore
from app.core.config import settings

logger = logging.getLogger(__name__)
_BACKGROUND_TASKS: set[asyncio.Task] = set()

VALID_CATEGORIES = {"基础设施", "测试用例", "开发代码", "其他"}

CATEGORY_KEYWORDS = {
    "基础设施": ["runner", "environment", "install", "setup", "driver", "pip",
                 "network", "disk", "memory", "npu", "docker", "依赖", "环境"],
    "测试用例": ["test", "assert", "flaky", "断言", "测试数据", "不稳定"],
    "开发代码": ["bug", "logic", "null", "pointer", "exception", "接口",
                 "空指针", "逻辑", "代码"],
}


class FailureAnalysisService:

    def __init__(self):
        self.file_store = FailureAnalysisFileStore()

    @staticmethod
    def _data_root() -> Path:
        """Resolve the shared data directory consistently on host and Docker."""
        root = Path(settings.DATA_DIR)
        if not root.is_absolute():
            root = Path.cwd() / root
        return root.resolve()

    async def _get_llm_config(self, db: AsyncSession):
        stmt = select(LLMProviderConfig).where(LLMProviderConfig.is_active == True).limit(1)
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()
        if not config:
            raise ValueError("No active LLM provider configured")
        if not config.api_key:
            raise ValueError(f"API Key not configured for provider: {config.provider}")
        return config

    async def _get_agent_config(self, db: AsyncSession) -> dict:
        """Read failure-analysis Agent runtime limits."""
        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == "failure_analysis_agent_config"
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row and row.config_value:
            return {"runtime": "claude_cli", **dict(row.config_value)}
        # One-time compatibility with the former UI storage key. Legacy rows
        # contain only limits and therefore intentionally stay on Claude CLI.
        legacy_stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == "claude_code_cli_config"
        )
        legacy = (await db.execute(legacy_stmt)).scalar_one_or_none()
        if legacy and legacy.config_value:
            return {"runtime": "claude_cli", **dict(legacy.config_value)}
        # Safe upgrade default: keep the established Claude Code CLI path until
        # an administrator explicitly enables the custom evidence Agent.
        return {"runtime": "claude_cli", "max_turns": 80, "timeout_seconds": 1800}

    def _get_default_prompt(self) -> str:
        from app.services.skill_registry import get_skill_registry
        registry = get_skill_registry()
        skill = registry.get_skill_by_scope("ci_failure_analysis")
        if skill and skill.content:
            return skill.content
        return "你是专业的 CI/CD 失败诊断分析师。请根据提供的 CI Job 失败信息、日志、artifact、历史成功记录和代码仓证据，进行根因分析并给出改进建议。"

    @staticmethod
    def _normalize_matrix_ref(value: str | None) -> str | None:
        """Normalize a matrix/job ref token into a git ref when possible."""
        if not value:
            return None
        ref = value.strip().strip("`'\"")
        if not ref or ref.lower() in {"unknown", "none", "null"}:
            return None
        # GitHub matrix values often replace the slash in release branches to
        # make job names/docker tags friendlier: releases-vX.Y.Z -> releases/vX.Y.Z.
        if re.fullmatch(r"releases-v\d+(?:\.\d+)+(?:[-._A-Za-z0-9]*)?", ref):
            return ref.replace("releases-", "releases/", 1)
        return ref

    @classmethod
    def _infer_matrix_target_ref_from_job_name(cls, job_name: str | None) -> str | None:
        """Infer the tested source ref from the first matrix field in a job name.

        Example:
            single-node (releases-vX.Y.Z, model, runner, config)
            -> releases/vX.Y.Z
        """
        if not job_name:
            return None
        match = re.search(r"\(([^,\)]+)", job_name)
        if not match:
            return None
        token = match.group(1).strip()
        # Avoid treating a model name or runner label as a ref in non-matrix jobs.
        if not re.match(r"^(main|master|release|releases[-/]|v\d|[0-9a-f]{7,40}\b)", token, re.IGNORECASE):
            return None
        return cls._normalize_matrix_ref(token)

    @staticmethod
    def _extract_tested_repo_ref_from_log(log_path: str | None) -> dict[str, str | None]:
        """Extract the vllm-ascend checkout branch/commit from a GitHub job log.

        The workflow run itself can be on `main` while the matrix tests a
        release branch.  The authoritative code boundary for diagnosis is the
        checkout printed inside the job log, not CIResult.head_sha.
        """
        info: dict[str, str | None] = {"branch": None, "commit": None, "version": None}
        if not log_path:
            return info
        try:
            text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return info

        # Prefer the explicit env/version value emitted by the CI setup.
        version_matches = re.findall(r"\bVLLM_ASCEND_VERSION:\s*([0-9a-f]{40})\b", text, re.IGNORECASE)
        if version_matches:
            info["version"] = version_matches[-1]

        # The setup step prints two repos.  The vllm-ascend checkout is the one
        # whose following lines show the matrix/release branch rather than HEAD.
        branch_commit_pairs = re.findall(
            r"Branch:\s+([^\r\n]+)\r?\n[^\r\n]*Commit hash:\s*([0-9a-f]{40})",
            text,
            re.IGNORECASE,
        )
        for branch, commit in branch_commit_pairs:
            branch = branch.strip()
            if branch and branch.upper() != "HEAD":
                info["branch"] = branch
                info["commit"] = commit
        if not info["commit"] and info["version"]:
            info["commit"] = info["version"]

        # Some workflows print input values instead of checkout summary.
        explicit_ref = re.search(r"\bvllm_ascend_ref:\s*([0-9a-f]{7,40}|[A-Za-z0-9._/@{}^~:+-]+)", text, re.IGNORECASE)
        if explicit_ref and not info["commit"]:
            info["commit"] = explicit_ref.group(1).strip()
        explicit_branch = re.search(r"\bvllm_ascend_branch:\s*([A-Za-z0-9._/@{}^~:+-]+)", text, re.IGNORECASE)
        if explicit_branch and not info["branch"]:
            info["branch"] = explicit_branch.group(1).strip()

        return info

    async def _get_system_prompt(self, db: AsyncSession) -> str:
        stmt = select(ProjectDashboardConfig).where(
            ProjectDashboardConfig.config_key == 'ci_failure_analysis_system_prompt'
        )
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()
        if config and config.config_value:
            value = config.config_value
            if isinstance(value, dict):
                return value.get('default', self._get_default_prompt())
            if isinstance(value, str):
                return value
        return self._get_default_prompt()

    async def analyze_failed_job(self, job_id: int, db: AsyncSession, force: bool = False, triggered_by: str = "manual"):
        stmt = select(CIJob).where(CIJob.job_id == job_id)
        result = await db.execute(stmt)
        job = result.scalar_one_or_none()
        if not job:
            raise ValueError(f"CIJob with job_id={job_id} not found")
        if job.conclusion not in ("failure", "cancelled"):
            raise ValueError(f"CIJob {job_id} conclusion is '{job.conclusion}', not a failed/cancelled job")

        existing_stmt = select(JobFailureAnalysis).where(
            JobFailureAnalysis.job_id == job_id
        ).order_by(JobFailureAnalysis.id.desc()).limit(1)
        existing_result = await db.execute(existing_stmt)
        existing = existing_result.scalar_one_or_none()
        if existing and existing.analysis_status in ("completed", "reused") and not force:
            return existing

        fingerprint = self.compute_failure_fingerprint(job)
        llm_config = await self._get_llm_config(db)

        # 鎸囩汗澶嶇敤锛堜粎 scheduler 瑙﹀彂锛屾墜鍔?force=true 璺宠繃锛?
        if not force:
            dedup_stmt = select(JobFailureAnalysis).where(
                and_(
                    JobFailureAnalysis.failure_fingerprint == fingerprint,
                    JobFailureAnalysis.analysis_status == "completed",
                    JobFailureAnalysis.job_id != job_id,
                )
            ).limit(1)
            dedup_result = await db.execute(dedup_stmt)
            dedup_match = dedup_result.scalar_one_or_none()
            if dedup_match:
                target = existing if existing else JobFailureAnalysis(
                    job_id=job_id, run_id=job.run_id,
                    workflow_name=job.workflow_name, job_name=job.job_name,
                    failure_date=job.completed_at or datetime.now(UTC),
                )
                target.failure_fingerprint = fingerprint
                target.reused_analysis_id = dedup_match.id
                target.problem_category = dedup_match.problem_category
                target.root_cause_summary = dedup_match.root_cause_summary
                target.improvement_measures_summary = dedup_match.improvement_measures_summary
                target.report_file_path = dedup_match.report_file_path
                target.llm_provider = dedup_match.llm_provider or llm_config.provider
                target.llm_model = dedup_match.llm_model or llm_config.default_model
                target.analysis_status = "reused"
                target.triggered_by = triggered_by
                if target not in db:
                    db.add(target)
                await db.commit()
                await db.refresh(target)
                return target

        # 浠庢暟鎹簱璇诲彇 CLI 閰嶇疆锛堥粯璁ゅ€煎厹搴曪級
        agent_config = await self._get_agent_config(db)
        runtime = str(agent_config.get("runtime", "claude_cli")).strip().lower()
        if runtime not in {"claude_cli", "custom_agent"}:
            logger.warning("Unknown failure-analysis runtime %r; using claude_cli", runtime)
            runtime = "claude_cli"
        max_turns_val = max(3, min(int(agent_config.get("max_turns", 80)), 100))
        timeout_val = max(60, min(int(agent_config.get("timeout_seconds", 1800)), 7200))
        system_prompt = await self._get_system_prompt(db)
        user_prompt = await self._build_job_context(job, db, max_turns=max_turns_val, timeout_seconds=timeout_val)

        # 濡傛灉涔嬪墠鏈夊け璐?鍗′綇鐨勮褰曪紝澶嶇敤鑰屼笉鏄彃鍏ユ柊璁板綍锛堥伩鍏?UNIQUE 鍐茬獊锛?
        if existing:
            analysis = existing
            analysis.analysis_status = "analyzing"
            analysis.error_message = None
            analysis.failure_fingerprint = fingerprint
            analysis.triggered_by = triggered_by
        else:
            analysis = JobFailureAnalysis(
                job_id=job_id,
                run_id=job.run_id,
                workflow_name=job.workflow_name,
                job_name=job.job_name,
                failure_date=job.completed_at or datetime.now(UTC),
                failure_fingerprint=fingerprint,
                triggered_by=triggered_by,
                analysis_status="analyzing",
            )
            db.add(analysis)
        await db.flush()
        await db.refresh(analysis)

        try:
            provider_config = {
                "provider": llm_config.provider,
                "api_key": llm_config.decrypted_api_key,
                "api_base_url": llm_config.api_base_url,
                "default_model": llm_config.default_model,
            }
            if runtime == "custom_agent":
                llm_result = await self._run_evidence_pipeline(
                    job_context=user_prompt,
                    provider_config=provider_config,
                    system_prompt=system_prompt,
                    analysis=analysis,
                    db=db,
                    max_steps=max_turns_val,
                    timeout_seconds=timeout_val,
                )
                executed_steps = llm_result.steps
            else:
                from app.services.claude_code_cli import run_with_fallback

                logger.info("Failure analysis job %s routed to claude-code-cli", job_id)
                analysis.analysis_phase = "claude_cli"
                llm_result = await run_with_fallback(
                    prompt=user_prompt,
                    provider_config=provider_config,
                    system_prompt=system_prompt,
                    max_turns=max_turns_val,
                    timeout_seconds=timeout_val,
                    output_format="json",
                )
                executed_steps = llm_result.turns
            # 娓呮礂 GLM-5.1 鐨?<think> 鍜?tool call 鍣煶
            raw = llm_result.content
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL)
            raw = re.sub(r'```bash\n.*?```', '', raw, flags=re.DOTALL)
            raw = re.sub(r'curl -sL.*?(?=\n\n|\Z)', '', raw, flags=re.DOTALL)
            raw = re.sub(r'LOGS=\$.*?(?=\n\n|\n#|\Z)', '', raw, flags=re.DOTALL)

            # CLI 娌℃湁瀹為檯杩愯锛坱urns=0 鎴栬緭鍑哄お鐭級
            if executed_steps == 0 and len(raw.strip()) < 50:
                raise RuntimeError(
                    f"{runtime} did not produce a valid analysis: "
                    f"steps={executed_steps}, content_len={len(raw)}"
                )

            # 妫€娴?LLM/API 灞傞敊璇細CLI 浼氭妸涓婃父 API 閿欒锛堝 400 Invalid model name锛?
            # 浣滀负 content 杩斿洖锛屾绫昏緭鍑轰笉鏄湁鏁堝垎鏋愮粨鏋滐紝搴旀爣璁颁负 failed
            # 鑰岄潪琚?parse_llm_response 鍏滃簳涓?completed/鍏朵粬
            api_err = self._detect_api_error(raw)
            if api_err:
                raise RuntimeError(f"LLM API error: {api_err}")

            report_json = self._extract_report_summary(raw)
            missing_report_fields = [
                key for key in (
                    "problem_category",
                    "root_cause_summary",
                    "improvement_measures_summary",
                )
                if not isinstance(report_json.get(key), str) or not report_json[key].strip()
            ]
            if missing_report_fields:
                raise RuntimeError(
                    "Report renderer returned an incomplete report; missing JSON fields: "
                    + ", ".join(missing_report_fields)
                )

            parsed = self.parse_llm_response(raw)
            if runtime == "custom_agent" and (
                (analysis.validation_result or {}).get("verdict") not in {"pass", "likely"}
                and not any(
                    marker in parsed.get("root_cause_summary", "").lower()
                    for marker in ("candidate", "unverified", "候选", "未验证", "可能", "推断", "证据不足")
                )
            ):
                parsed["root_cause_summary"] = (
                    "候选（证据不足）：" + parsed.get("root_cause_summary", "")
                )
            if not parsed.get("problem_category"):
                raise RuntimeError(
                    f"Failed to parse analysis result: {raw[:500]}"
                )
            report_content = parsed.get("full_report", raw)
            try:
                report_path = await self.file_store.save_report(
                    job.workflow_name, job.job_name, job_id, report_content
                )
            except OSError as e:
                logger.warning("Failed to save report file (non-fatal): %s", e)
                report_path = None

            analysis.analysis_status = "completed"
            analysis.analysis_phase = "completed"
            # 鐢熸垚鍏紑鍒嗕韩 token
            if not analysis.share_token:
                import secrets
                analysis.share_token = secrets.token_urlsafe(32)
            analysis.problem_category = self._clip_db_text(parsed["problem_category"], 20)
            analysis.root_cause_summary = self._clip_db_text(parsed["root_cause_summary"], 500)
            analysis.improvement_measures_summary = self._clip_db_text(
                parsed["improvement_measures_summary"], 500
            )
            analysis.report_file_path = report_path
            analysis.llm_provider = llm_config.provider
            analysis.llm_model = llm_config.default_model
            analysis.prompt_tokens = None  # CLI 妯″紡涓嶅彲鐢?
            analysis.completion_tokens = None
            analysis.generation_time_seconds = int(llm_result.duration_seconds)

            await db.commit()
            await db.refresh(analysis)
            # Commit the user-visible result before scheduling optional PDF work.
            if report_content:
                pdf_task = asyncio.create_task(self._generate_pdf_async(
                    analysis.id, report_content, job.workflow_name, job.job_name, job_id
                ))
                _BACKGROUND_TASKS.add(pdf_task)
                pdf_task.add_done_callback(_BACKGROUND_TASKS.discard)
        except Exception as e:
            await db.refresh(analysis)
            if analysis.analysis_status != "cancelled":
                analysis.analysis_status = "failed"
                analysis.analysis_phase = "failed"
                analysis.error_message = str(e)
            await db.commit()
            await db.refresh(analysis)
            logger.error(f"LLM analysis failed for job {job_id}: {e}")

        return analysis

    @staticmethod
    def _clip_db_text(value: object, limit: int) -> str:
        """Keep short DB summary columns from rejecting otherwise valid reports."""
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        suffix = "…"
        return text[: max(0, limit - len(suffix))].rstrip() + suffix

    async def _persist_pipeline_progress(
        self,
        analysis_id: int,
        phase: str,
        trace: list[dict],
    ) -> None:
        """Persist live agent progress using an isolated session."""
        try:
            from sqlalchemy import update
            from app.db.base import SessionLocal

            async with SessionLocal() as progress_db:
                await progress_db.execute(
                    update(JobFailureAnalysis)
                    .where(
                        JobFailureAnalysis.id == analysis_id,
                        JobFailureAnalysis.analysis_status == "analyzing",
                    )
                    .values(
                        analysis_phase=phase,
                        agent_trace=trace[-80:],
                        agent_steps=len(trace),
                        updated_at=datetime.now(UTC),
                    )
                )
                await progress_db.commit()
        except Exception as exc:
            logger.warning("Failed to persist agent progress: %s", exc)

    async def _heartbeat_pipeline_phase(
        self,
        analysis_id: int,
        phase: str,
        trace_ref: list[dict],
        interval_seconds: int = 20,
    ) -> None:
        """Keep analyzing jobs visibly alive while an LLM call is in flight.

        Step callbacks only fire after smolagents finishes a step.  A verifier
        or reporter final-answer call can legitimately take a few minutes, and
        without a heartbeat the UI and operators see a stale row and may
        misdiagnose it as a deadlock.  This heartbeat does not fabricate steps
        or conclusions; it only refreshes phase/updated_at and the latest trace.
        """
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                await self._persist_pipeline_progress(analysis_id, phase, list(trace_ref))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Failed to heartbeat analysis phase=%s: %s", phase, exc)

    async def _run_evidence_pipeline(
        self,
        *,
        job_context: str,
        provider_config: dict,
        system_prompt: str,
        analysis: JobFailureAnalysis,
        db: AsyncSession,
        max_steps: int,
        timeout_seconds: int,
    ):
        """Run investigation -> independent verification -> report rendering."""
        import asyncio

        from app.services.agent_service import AgentResult, AgentService, AgentTask
        from app.services.agent_tools import (
            FAILURE_ANALYSIS_TOOLS,
            grep_content,
            list_files,
            read_log_file,
            read_log_excerpt,
            git_show_commit,
            git_read_file,
            git_search_symbol,
            git_compare_file,
        )
        from app.services.failure_analysis_pipeline import (
            extract_json_object,
            extract_required_regression_candidates,
            enrich_ledger_from_trace,
            investigation_prompt,
            normalize_ledger,
            normalize_auditor_validation,
            programmatic_validate,
            revision_prompt,
            report_prompt,
            enforce_validation_on_report,
            verification_prompt,
        )
        from app.services.failure_analysis_knowledge_graph import (
            build_failure_analysis_knowledge_graph,
            summarize_graph_for_agent,
        )

        # Reserve the configured max_steps for the worst case:
        # investigation + verification + one revision + second verification + reporting.
        # If verifier passes on the first round, the reserved revision budget is simply unused.
        verifier_steps = min(12, max(6, int(max_steps * 0.14)))
        revision_steps = min(14, max(6, int(max_steps * 0.16)))
        reporter_steps = max(3, int(max_steps * 0.08))
        investigator_steps = max(1, max_steps - (verifier_steps * 2) - revision_steps - reporter_steps)
        investigator_timeout = max(30, int(timeout_seconds * 0.60))
        verifier_timeout = min(900, max(600, int(timeout_seconds * 0.25)))
        reporter_timeout = max(30, timeout_seconds - investigator_timeout - verifier_timeout)
        verifier_tools = [
            read_log_file,
            read_log_excerpt,
            grep_content,
            git_show_commit,
            git_read_file,
            git_search_symbol,
            git_compare_file,
        ]
        trace: list[dict] = list(analysis.agent_trace or [])
        loop = asyncio.get_running_loop()

        def callback_for(phase: str):
            def _callback(entry: dict):
                trace.append(entry)
                asyncio.run_coroutine_threadsafe(
                    self._persist_pipeline_progress(analysis.id, phase, list(trace)),
                    loop,
                )
            return _callback

        async def run_agent_with_heartbeat(task: AgentTask, phase: str) -> AgentResult:
            logger.info(
                "FailureAnalysis pipeline phase=%s starting max_steps=%s timeout=%ss",
                phase,
                task.max_steps,
                task.timeout_seconds,
            )
            heartbeat = asyncio.create_task(
                self._heartbeat_pipeline_phase(analysis.id, phase, trace)
            )
            started = datetime.now(UTC)
            try:
                result = await AgentService(db).run(task)
                logger.info(
                    "FailureAnalysis pipeline phase=%s finished exit=%s steps=%s duration=%.1fs",
                    phase,
                    result.exit_code,
                    result.steps,
                    (datetime.now(UTC) - started).total_seconds(),
                )
                return result
            finally:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass

        analysis.analysis_phase = "investigation"
        analysis.evidence_ledger = None
        analysis.validation_result = None
        analysis.agent_trace = []
        analysis.agent_steps = 0
        await db.commit()

        required_candidates = extract_required_regression_candidates(job_context)

        investigator = await run_agent_with_heartbeat(AgentTask(
            prompt=investigation_prompt(job_context),
            provider_config=provider_config,
            system_prompt=system_prompt,
            max_steps=investigator_steps,
            timeout_seconds=investigator_timeout,
            memory_type="failure_analysis",
            source_id=analysis.id,
            tools_override=FAILURE_ANALYSIS_TOOLS,
            step_callback=callback_for("investigation"),
            phase="investigation",
        ), "investigation")
        if investigator.exit_code != 0:
            raise RuntimeError(investigator.error_message or "Investigation agent failed")
        await db.refresh(analysis)
        if analysis.analysis_status == "cancelled":
            raise RuntimeError("Analysis cancelled")
        ledger = enrich_ledger_from_trace(
            normalize_ledger(extract_json_object(investigator.content)),
            trace,
        )
        if required_candidates:
            ledger["required_regression_candidates"] = required_candidates
        program_validation = programmatic_validate(ledger, required_candidates)
        analysis.evidence_ledger = ledger
        analysis.analysis_phase = "verification"
        analysis.agent_trace = trace[-80:]
        analysis.agent_steps = len(trace)
        await db.commit()

        blocking_findings = [
            item for item in program_validation.get("findings", [])
            if item.get("severity") == "error"
            and item.get("code") in {
                "missing_hypotheses",
                "missing_failure_facts",
                "missing_regression_boundary",
            }
        ]
        if blocking_findings:
            analysis.validation_result = {
                "verdict": "insufficient",
                "programmatic": program_validation,
                "auditor": {
                    "verdict": "revise",
                    "findings": [
                        "investigation 阶段未产出可审计的结构化 evidence ledger；"
                        "为避免 verifier 从零重新调查并产生漂移结论，已阻止进入审计阶段。"
                    ],
                    "required_changes": [
                        "补齐 failure_facts、regression_boundary 和至少一个带代码/日志证据的 hypothesis 后再运行 verifier。"
                    ],
                },
            }
            analysis.analysis_phase = "investigation_failed"
            analysis.agent_trace = trace[-80:]
            analysis.agent_steps = len(trace)
            await db.commit()
            codes = ", ".join(str(item.get("code")) for item in blocking_findings)
            raise RuntimeError(f"Investigation produced an incomplete evidence ledger: {codes}")

        graph_summary = summarize_graph_for_agent(build_failure_analysis_knowledge_graph(analysis))
        ledger["knowledge_graph_memory"] = graph_summary
        analysis.evidence_ledger = ledger
        await db.commit()

        verifier = await run_agent_with_heartbeat(AgentTask(
            prompt=verification_prompt(ledger, graph_summary),
            provider_config=provider_config,
            system_prompt=(
                "你是独立 CI 证据审计员。必须审计 evidence ledger 是否自洽、是否存在被单一标签误排除的候选、"
                "是否完成日志↔代码仓往返验证。你不是第二个调查员：不要重新完整调查，不要枚举目录，不要使用 shell。"
                "只能少量调用受控工具核对关键日志片段和 git 代码/commit 证据。"
                "如果证据链闭合但无法重跑 benchmark，返回 likely；不要仅因无法复跑降为 insufficient。"
                "最终只能返回 JSON audit。"
            ),
            max_steps=verifier_steps,
            timeout_seconds=verifier_timeout,
            memory_type="failure_analysis",
            source_id=analysis.id,
            tools_override=verifier_tools,
            step_callback=callback_for("verification"),
            phase="verification",
        ), "verification")
        if verifier.exit_code != 0:
            verifier_error = verifier.error_message or "Evidence verifier failed"
            if program_validation.get("verdict") != "pass":
                raise RuntimeError(verifier_error)
            auditor_validation = {
                "verdict": "likely",
                "fallback": True,
                "findings": [
                    "独立 verifier 在审计过程中被模型超时/中断，未能返回完整 JSON audit；"
                    "系统没有丢弃 investigation 证据，而是基于程序化门禁结果降级为 likely。"
                ],
                "approved_claims": [
                    "investigation 已产出失败事实、last-good/bad 边界和候选假设，且通过结构化门禁。"
                ],
                "rejected_claims": [],
                "required_changes": [
                    "下次分析应继续让 verifier 审计候选假设的日志↔代码调用链；"
                    f"本次 verifier 错误：{verifier_error}",
                ],
                "report_constraints": [
                    "最终报告只能使用“主要嫌疑/高置信候选/待运行复现”，不能写成确认根因。",
                    "必须明确说明 verifier 因模型超时中断，审计结果为降级 fallback。",
                ],
            }
        else:
            auditor_validation = normalize_auditor_validation(extract_json_object(verifier.content))

        async def maybe_run_revision(
            current_ledger: dict,
            current_program_validation: dict,
            current_auditor_validation: dict,
        ) -> tuple[dict, dict, dict]:
            auditor_verdict_for_revision = str(
                current_auditor_validation.get("verdict", "insufficient")
            ).lower()
            required_changes = current_auditor_validation.get("required_changes")
            weak_graph = (current_ledger.get("knowledge_graph_memory") or {}).get("weak_hypotheses") or []
            needs_revision = (
                auditor_verdict_for_revision in {"revise", "insufficient"}
                and (required_changes or weak_graph)
            )
            if not needs_revision:
                return current_ledger, current_program_validation, current_auditor_validation

            analysis.analysis_phase = "revision"
            analysis.validation_result = {
                "verdict": "revise",
                "programmatic": current_program_validation,
                "auditor": current_auditor_validation,
                "closed_loop": {
                    "status": "revision_started",
                    "reason": "verifier requested evidence repair or graph memory found weak hypotheses",
                },
            }
            await db.commit()

            revision = await run_agent_with_heartbeat(AgentTask(
                prompt=revision_prompt(
                    job_context,
                    current_ledger,
                    current_ledger.get("knowledge_graph_memory") or {},
                    current_auditor_validation,
                ),
                provider_config=provider_config,
                system_prompt=system_prompt,
                max_steps=revision_steps,
                timeout_seconds=min(900, max(300, int(timeout_seconds * 0.18))),
                memory_type="failure_analysis",
                source_id=analysis.id,
                tools_override=FAILURE_ANALYSIS_TOOLS,
                step_callback=callback_for("revision"),
                phase="investigation",
            ), "revision")
            if revision.exit_code != 0:
                fallback = dict(current_auditor_validation)
                fallback.setdefault("findings", [])
                fallback["findings"] = list(fallback.get("findings") or []) + [
                    f"闭环修正阶段失败：{revision.error_message or 'revision agent failed'}"
                ]
                return current_ledger, current_program_validation, fallback

            revised_ledger = enrich_ledger_from_trace(
                normalize_ledger(extract_json_object(revision.content)),
                trace,
            )
            if required_candidates:
                revised_ledger["required_regression_candidates"] = required_candidates
            revised_program_validation = programmatic_validate(revised_ledger, required_candidates)
            analysis.evidence_ledger = revised_ledger
            analysis.analysis_phase = "verification"
            analysis.agent_trace = trace[-80:]
            analysis.agent_steps = len(trace)
            await db.commit()

            revised_graph_summary = summarize_graph_for_agent(build_failure_analysis_knowledge_graph(analysis))
            revised_ledger["knowledge_graph_memory"] = revised_graph_summary
            analysis.evidence_ledger = revised_ledger
            await db.commit()

            revised_verifier = await run_agent_with_heartbeat(AgentTask(
                prompt=verification_prompt(revised_ledger, revised_graph_summary),
                provider_config=provider_config,
                system_prompt=(
                    "你是独立 CI 证据审计员。现在正在审计修正后的 evidence ledger。"
                    "重点确认 verifier 上一轮指出的缺口是否被补齐；不要重新完整调查。最终只返回 JSON audit。"
                ),
                max_steps=verifier_steps,
                timeout_seconds=verifier_timeout,
                memory_type="failure_analysis",
                source_id=analysis.id,
                tools_override=verifier_tools,
                step_callback=callback_for("verification"),
                phase="verification",
            ), "verification")
            if revised_verifier.exit_code != 0:
                revised_auditor_validation = {
                    "verdict": "insufficient",
                    "findings": [revised_verifier.error_message or "revised verifier failed"],
                    "closed_loop": {"status": "revision_done_verifier_failed"},
                }
            else:
                revised_auditor_validation = normalize_auditor_validation(
                    extract_json_object(revised_verifier.content)
                )
            revised_auditor_validation["closed_loop"] = {
                "status": "revision_done",
                "previous_verdict": auditor_verdict_for_revision,
            }
            return revised_ledger, revised_program_validation, revised_auditor_validation

        ledger, program_validation, auditor_validation = await maybe_run_revision(
            ledger,
            program_validation,
            auditor_validation,
        )
        await db.refresh(analysis)
        if analysis.analysis_status == "cancelled":
            raise RuntimeError("Analysis cancelled")
        auditor_verdict = str(auditor_validation.get("verdict", "insufficient")).lower()
        program_has_error = any(
            item.get("severity") == "error"
            for item in program_validation.get("findings", [])
        )
        if not program_has_error and auditor_verdict == "pass":
            verdict = "pass"
        elif not program_has_error and auditor_verdict in {"likely", "probable"}:
            verdict = "likely"
        else:
            verdict = "insufficient"
        validation = {
            "verdict": verdict,
            "programmatic": program_validation,
            "auditor": auditor_validation,
        }
        analysis.validation_result = validation
        analysis.analysis_phase = "reporting"
        analysis.agent_trace = trace[-80:]
        analysis.agent_steps = len(trace)
        await db.commit()

        reporter = await run_agent_with_heartbeat(AgentTask(
            prompt=report_prompt(ledger, validation, ledger.get("knowledge_graph_memory")),
            provider_config=provider_config,
            system_prompt=(
                "你是中文 CI 分析报告生成器。只能根据给定的已验证证据生成简体中文报告，"
                "不得发明事实或增强任何结论。代码、路径、commit、PR、命令和日志引用保持原文。"
            ),
            max_steps=reporter_steps,
            timeout_seconds=reporter_timeout,
            tools_override=[],
            step_callback=callback_for("reporting"),
            phase="reporting",
        ), "reporting")
        if reporter.exit_code != 0:
            raise RuntimeError(reporter.error_message or "Report renderer failed")
        await db.refresh(analysis)
        if analysis.analysis_status == "cancelled":
            raise RuntimeError("Analysis cancelled")

        safe_report = enforce_validation_on_report(reporter.content, validation)
        analysis.analysis_phase = "completed"
        analysis.agent_trace = trace[-80:]
        analysis.agent_steps = len(trace)
        analysis.evidence_ledger = ledger
        analysis.validation_result = validation
        await db.commit()
        return AgentResult(
            content=safe_report,
            steps=len(trace),
            duration_seconds=(
                investigator.duration_seconds + verifier.duration_seconds + reporter.duration_seconds
            ),
            model_used=reporter.model_used,
            trace=trace,
        )

    async def analyze_batch(self, days_back: int, db: AsyncSession):
        cutoff = datetime.now(UTC) - timedelta(days=days_back)
        stmt = select(CIJob).where(
            and_(
                CIJob.conclusion.in_(["failure", "cancelled"]),
                CIJob.completed_at >= cutoff,
            )
        )
        result = await db.execute(stmt)
        jobs = result.scalars().all()

        analysed_stmt = select(JobFailureAnalysis.job_id).where(
            JobFailureAnalysis.analysis_status.in_(["completed", "reused"])
        )
        analysed_result = await db.execute(analysed_stmt)
        analysed_ids = set(analysed_result.scalars().all())

        results = []
        for job in jobs:
            if job.job_id in analysed_ids:
                continue
            try:
                analysis = await self.analyze_failed_job(job.job_id, db)
                results.append(analysis)
            except Exception as e:
                logger.error(f"Batch analysis failed for job {job.job_id}: {e}")
        return results

    async def _build_job_context(self, job: CIJob, db: AsyncSession, max_turns: int = 80, timeout_seconds: int = 1800, inline_logs: bool = False) -> str:
        timeout_min = timeout_seconds // 60
        lines = []
        if inline_logs:
            lines.append("请分析以下 CI 失败，直接基于已内联的数据输出分析报告。")
        else:
            lines.append("请使用 auto-bug-fixer 技能分析以下 CI 失败。")
        lines.append("")
        lines.append("以下数据已预加载，请直接基于这些数据分析，无需 curl 拉取：")
        lines.append("- Annotations（下方）")
        lines.append("- Steps summary（下方）")
        lines.append("- 历史运行对比（下方）")
        lines.append("- Commit diff（下方）")
        lines.append("- CI Job 原始日志（下方，已截取关键部分）")
        lines.append("")
        lines.append("如需更多数据（多节点日志、artifacts 等），优先使用已下载到 backend/data 的文件和代码仓缓存进行分析。")
        lines.append("")
        lines.append("## CI Job 失败信息\n")
        lines.append(f"- **Workflow**: {job.workflow_name}")
        lines.append(f"- **Job Name**: {job.job_name}")
        lines.append(f"- **Hardware**: {job.hardware or 'unknown'}")
        lines.append(f"- **Runner**: {job.runner_name or 'unknown'}")
        try:
            labels = json.loads(job.runner_labels) if job.runner_labels else []
            if isinstance(labels, list):
                lines.append(f"- **Runner Labels**: {', '.join(labels)}")
            else:
                lines.append(f"- **Runner Labels**: {labels}")
        except (json.JSONDecodeError, TypeError):
            lines.append(f"- **Runner Labels**: {job.runner_labels or 'unknown'}")
        lines.append(f"- **Conclusion**: {job.conclusion}")
        lines.append(f"- **Duration**: {job.duration_seconds or 'unknown'}s")
        lines.append(f"- **Started At**: {job.started_at or 'unknown'}")
        lines.append(f"- **Completed At**: {job.completed_at or 'unknown'}")

        # 鑾峰彇鍏宠仈鐨?CIResult锛堝惈 branch 鍜?head_sha锛?
        ci_result = await self._get_ci_result(db, job.run_id)
        if ci_result:
            lines.append(f"- **Workflow Branch**: {ci_result.branch or 'unknown'}")
            lines.append(f"- **Workflow Head SHA**: `{ci_result.head_sha}`" if ci_result.head_sha else "")

        # 预先下载日志并抽取真正被测源码 ref。对矩阵 job，workflow 可能来自 main，
        # 但容器里 checkout 的 vllm-ascend 可能是 releases/vX.Y.Z。
        logs = await self._download_all_logs(job)
        matrix_target_ref = self._infer_matrix_target_ref_from_job_name(job.job_name)
        tested_ref = self._extract_tested_repo_ref_from_log(logs.get("job_log"))
        tested_branch = tested_ref.get("branch") or matrix_target_ref
        tested_commit = tested_ref.get("commit")
        if matrix_target_ref or tested_branch or tested_commit:
            lines.append(f"- **Matrix/Code Target Ref**: `{tested_branch or matrix_target_ref or 'unknown'}`")
            if tested_commit:
                lines.append(f"- **Tested vllm-ascend Commit**: `{tested_commit}`")
            if ci_result and tested_branch and ci_result.branch and tested_branch != ci_result.branch:
                lines.append(
                    "- **重要边界说明**: Workflow Branch/Head SHA 只标识本次 GitHub Actions workflow；"
                    "本 Job 的代码回归分析必须使用 Matrix/Code Target Ref 与 Tested vllm-ascend Commit，"
                    "禁止把 workflow main 的 PR/commit 当作候选根因。"
                )

        try:
            steps = json.loads(job.steps_data) if job.steps_data else []
            failed_steps = []
            all_steps_summary = []
            for step in steps:
                step_name = step.get("name", "unknown")
                step_conclusion = step.get("conclusion", "")
                step_number = step.get("number", "")
                step_started = step.get("started_at", "")
                step_completed = step.get("completed_at", "")
                step_status = step.get("status", "")

                if step_conclusion in ("failure", "timed_out", "startup_failure"):
                    duration_info = ""
                    if step_started and step_completed:
                        try:
                            from datetime import datetime as dt
                            s = dt.fromisoformat(step_started.replace("Z", "+00:00"))
                            e = dt.fromisoformat(step_completed.replace("Z", "+00:00"))
                            secs = int((e - s).total_seconds())
                            duration_info = f" (鑰楁椂 {secs}s)"
                        except Exception:
                            pass
                    failed_steps.append(f"  - Step #{step_number} `{step_name}` 鈫?{step_conclusion}{duration_info}")
                elif step_status == "completed" and step_conclusion == "success":
                    continue
                else:
                    all_steps_summary.append(f"  - Step #{step_number} `{step_name}` 鈫?status={step_status}, conclusion={step_conclusion}")

            if failed_steps:
                lines.append(f"\n### Failed Steps:\n")
                lines.extend(failed_steps)
                lines.append(
                    "\n以上失败步骤名称来自 GitHub steps_data。分析时应在完整 Job 日志中定位这些步骤对应的时间段和失败片段；"
                    "不要假设失败入口一定叫 stream log，步骤名称可能是 Run Pytest (xxx)、Run Test、Check、Capture 等。"
                )

            if all_steps_summary:
                lines.append(f"\n### Other Non-Success Steps:\n")
                lines.extend(all_steps_summary)
        except (json.JSONDecodeError, TypeError):
            lines.append(f"- **Steps Data**: (unparseable)")

        annotations = await self._fetch_job_annotations(job.job_id, db)
        if annotations:
            lines.append(f"\n### GitHub Actions Annotations (鍏抽敭閿欒淇℃伅):\n")
            for ann in annotations:
                level = ann.get("annotation_level", "notice")
                title = ann.get("title", "")
                message = ann.get("message", "")
                path_info = ann.get("path", "")
                if title:
                    lines.append(f"  - [{level}] **{title}**: {message}")
                else:
                    lines.append(f"  - [{level}] {message}")

        historical_comparison = await self._fetch_historical_run_comparison(job, db)
        if historical_comparison:
            lines.append(historical_comparison)

        commit_diff = await self._fetch_commit_diff(
            job,
            db,
            matrix_target_ref=matrix_target_ref,
            tested_branch=tested_branch,
            tested_commit=tested_commit,
            workflow_branch=ci_result.branch if ci_result else None,
            failure_context=self._extract_failure_context_for_candidate_ranking(logs.get("job_log")),
        )
        if commit_diff:
            lines.append(commit_diff)

        # 纭繚鏈湴 Git 浠撳簱宸?clone
        from app.services.github_cache import ensure_repo_cloned, get_github_cache
        ensure_repo_cloned()
        repo_path = str(get_github_cache().cache_dir.resolve())
        ref_value = tested_commit or (ci_result.head_sha if ci_result and ci_result.head_sha else "main")

        # 棰勬媺鍙栨墍鏈夊彲鐢ㄦ棩蹇楀埌鏈湴锛孋LI 鍙鏈湴鏂囦欢涓?curl
        if inline_logs:
            lines.append("\n### 本地已缓存的数据（已内联，无需额外拉取）\n")
            if logs["job_log"]:
                try:
                    from pathlib import Path
                    log_text = Path(logs["job_log"]).read_text(encoding="utf-8", errors="replace")
                    if len(log_text) > 20000:
                        log_text = "...(truncated)...\n" + log_text[-20000:]
                    lines.append(f"#### Job 日志:\n```\n{log_text}\n```\n")
                except Exception:
                    lines.append(f"- Job 日志文件：{logs['job_log']}（读取失败）")
        else:
            lines.append("\n### 本地已缓存的数据（请用工具直接读取，避免重复 curl）\n")
            if logs["job_log"]:
                lines.append(f"- Job 日志：`{logs['job_log']}`")
            if logs["run_log_zip"]:
                lines.append(f"- Run 全部日志 ZIP：`{logs['run_log_zip']}`，需要时读取解压后的相关 job 日志")
            if logs["artifacts_dir"]:
                lines.append(f"- Artifacts：`{logs['artifacts_dir']}`，需要时列目录并读取关键文件")
            if logs["jobs_list"]:
                lines.append(f"- Run 全部 job 列表：`{logs['jobs_list']}`，用于定位多节点/worker job 日志")
        lines.append("- Annotations、Steps、历史对比、Commit Diff：下方已预加载")
        lines.append(f"")
        lines.append("**源码分析工具建议：**")
        lines.append("  grep_content(pattern, log_path)               -> 先定位关键日志行号")
        lines.append("  read_log_excerpt(log_path, start, end)        -> 按行号读取失败附近片段；大日志禁止反复整文件读取")
        lines.append("  git_commit_range(last_good_tested_sha, bad_tested_sha)  -> 完整回归提交区间")
        lines.append("  git_show_commit(candidate_sha, path)          -> 候选提交 message + 真实 diff")
        lines.append("  git_read_file(ref, path, start, end)          -> 指定版本完整源码上下文")
        lines.append("  git_search_symbol(ref, symbol, path)          -> 搜索定义、调用点、配置和消费者")
        lines.append("  git_compare_file(last_good, bad_head, path)   -> 对比两个版本完整文件")
        lines.append(f"  失败被测代码 commit/ref：`{ref_value}`")
        if ci_result and ci_result.head_sha and tested_commit and ci_result.head_sha != tested_commit:
            lines.append(f"  Workflow head（不要当作代码边界）：`{ci_result.head_sha}`")
        lines.append("")
        lines.append("  从完整 Job 日志和 Failed Steps 对应片段切入，但代码仓贯穿全程；失败步骤不一定叫 stream log，可能是 Run Pytest (xxx) 或其他名称。发现代码线索后按对应 ref 读代码，再回到日志/artifact 验证，反复迭代。")
        lines.append("  可随时读取 last-good、bad/head 和区间内候选提交；使用结构化 Git 工具，无需 checkout 或修改工作树。")
        lines.append("  必须确认同一 Job 上次成功时间与被测代码 SHA，并建立 last-good-tested..bad-tested 回归区间。")
        lines.append("  如果 Matrix/Code Target Ref 与 Workflow Branch 不一致，必须从 job log/历史 job log 中抽取被测代码 SHA；抽不到时不要使用 workflow/main 的 commit diff。")
        lines.append("  候选提交必须检查新增/修改测试、调用方、配置入口、运行路径证据和反证。")
        lines.append("  日志来源是 GitHub Actions 下载到 backend/data 的 job/run 日志和 artifacts；不能登录 runner。")
        lines.append("  生产环境、当前 Job Runner 与本地分析宿主可能不同，不能混淆。")
        lines.append("")
        github_url = f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/runs/{job.run_id}/job/{job.job_id}"
        lines.append(f"\n- **GitHub Job URL**: {github_url}")
        lines.append("\n请按 CI 失败分析报告模板输出中文报告。")
        lines.append("\n报告末尾必须包含 JSON 代码块，key 名不可修改：")
        lines.append("```json")
        lines.append('{"problem_category": "基础设施|测试用例|开发代码|其他", "root_cause_summary": "根因摘要", "improvement_measures_summary": "改进措施摘要"}')
        lines.append("```")
        lines.append(f"\n轮次上限为 {max_turns}；完成足够证据后可以提前停止，不必跑满。")
        lines.append("\n根因分析必须在日志、artifact、代码仓、commit diff、调用链和相关测试之间往返验证；如果证据链未闭合，保持候选/证据不足措辞。")
        return "\n".join(lines)

    async def _fetch_job_annotations(self, job_id: int, db: AsyncSession) -> list[dict]:
        try:
            from app.services.github_client import GitHubClient
            github_token = settings.GITHUB_TOKEN
            if not github_token:
                logger.warning("GitHub token not configured, cannot fetch annotations")
                return []
            client = GitHubClient(token=github_token, owner=settings.GITHUB_OWNER, repo=settings.GITHUB_REPO)
            url = f"/repos/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/jobs/{job_id}/annotations"
            response = await client._request("GET", url)
            if isinstance(response, list):
                return response
            if isinstance(response, dict) and 'items' in response:
                return response.get('items', [])
            return []
        except Exception as e:
            logger.warning(f"Failed to fetch annotations for job {job_id}: {e}")
            return []

    async def _fetch_historical_run_comparison(self, job: CIJob, db: AsyncSession) -> str:
        stmt = select(CIResult).where(
            and_(
                CIResult.workflow_name == job.workflow_name,
                CIResult.conclusion.in_(["success", "failure", "cancelled"]),
            )
        ).order_by(desc(CIResult.completed_at)).limit(10)
        result = await db.execute(stmt)
        recent_runs = result.scalars().all()

        if not recent_runs:
            return "（无历史运行数据）"

        lines = []
        lines.append("\n### 历史运行对比（同 Workflow 最近 10 次运行中此 Job 的状态）\n")

        current_run_id = job.run_id
        for run in recent_runs:
            job_stmt = select(CIJob).where(
                and_(
                    CIJob.run_id == run.run_id,
                    CIJob.job_name == job.job_name,
                )
            ).limit(1)
            job_result = await db.execute(job_stmt)
            historical_job = job_result.scalar_one_or_none()

            is_current = run.run_id == current_run_id
            marker = " -> **当前失败**" if is_current else ""

            run_url = f"https://github.com/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/runs/{run.run_id}"
            if historical_job:
                job_conclusion = historical_job.conclusion or "unknown"
                lines.append(
                    f"- Run #{run.run_number} (SHA `{run.head_sha[:7]}`) -> "
                    f"workflow结论={run.conclusion}, 此Job={job_conclusion}"
                    f"{marker}  [链接]({run_url})"
                )
            else:
                lines.append(
                    f"- Run #{run.run_number} (SHA `{run.head_sha[:7]}`) -> "
                    f"workflow结论={run.conclusion}, 此Job=未记录"
                    f"{marker}  [链接]({run_url})"
                )

        # Do not derive last-good from the ten-run display window. The same job
        # may be skipped or absent for many workflow runs.
        last_success = await self._find_last_successful_job_run(job, db)

        skipped_count = 0
        executed_count = 0
        for run in recent_runs:
            job_stmt = select(CIJob).where(
                and_(
                    CIJob.run_id == run.run_id,
                    CIJob.job_name == job.job_name,
                )
            ).limit(1)
            job_result = await db.execute(job_stmt)
            h_job = job_result.scalar_one_or_none()
            if h_job:
                if h_job.conclusion == "skipped":
                    skipped_count += 1
                else:
                    executed_count += 1

        if skipped_count > 0 and executed_count <= 1:
            lines.append(f"\n**注意**: 此 Job 在最近的 {skipped_count} 次运行中为 skipped，本次可能是近期首次实际执行。")

        if last_success:
            lines.append(f"\n**上次成功运行**: Run #{last_success.run_number} (SHA `{last_success.head_sha[:7]}`, {last_success.completed_at})")

        return "\n".join(lines)

    async def _find_last_successful_job_run(
        self,
        job: CIJob,
        db: AsyncSession,
    ) -> CIResult | None:
        """Return the most recent successful run of this exact job before bad.

        A successful workflow is not sufficient: the target job itself must
        have executed successfully. This SHA is the last-good boundary used by
        both the historical summary and commit comparison.
        """
        cutoff = job.completed_at or job.started_at
        conditions = [
            CIResult.run_id == CIJob.run_id,
            CIResult.workflow_name == job.workflow_name,
            CIJob.workflow_name == job.workflow_name,
            CIJob.job_name == job.job_name,
            CIJob.conclusion == "success",
            CIResult.run_id != job.run_id,
        ]
        if cutoff is not None:
            conditions.append(CIResult.completed_at < cutoff)

        stmt = (
            select(CIResult)
            .join(CIJob, CIJob.run_id == CIResult.run_id)
            .where(and_(*conditions))
            .order_by(desc(CIResult.completed_at))
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _fetch_commit_diff(
        self,
        job: CIJob,
        db: AsyncSession,
        *,
        matrix_target_ref: str | None = None,
        tested_branch: str | None = None,
        tested_commit: str | None = None,
        workflow_branch: str | None = None,
        failure_context: str = "",
    ) -> str:
        current_run_stmt = select(CIResult).where(CIResult.run_id == job.run_id).limit(1)
        current_run_result = await db.execute(current_run_stmt)
        current_run = current_run_result.scalar_one_or_none()

        if not current_run:
            return ""

        last_success = await self._find_last_successful_job_run(job, db)

        if not last_success:
            return "\n### Commit 对比\n（无上次成功运行记录，无法进行 commit 对比）"

        target_ref = tested_branch or matrix_target_ref
        target_diff_required = bool(target_ref and workflow_branch and target_ref != workflow_branch)
        base_sha = last_success.head_sha
        head_sha = current_run.head_sha
        boundary_label = "Workflow Head"

        if target_diff_required:
            last_job_stmt = select(CIJob).where(
                and_(
                    CIJob.run_id == last_success.run_id,
                    CIJob.job_name == job.job_name,
                )
            ).limit(1)
            last_job_result = await db.execute(last_job_stmt)
            last_success_job = last_job_result.scalar_one_or_none()
            last_tested_commit = None
            if last_success_job:
                last_logs = await self._download_all_logs(last_success_job)
                last_tested_ref = self._extract_tested_repo_ref_from_log(last_logs.get("job_log"))
                last_tested_commit = last_tested_ref.get("commit")

            if not tested_commit or not last_tested_commit:
                return (
                    "\n### Commit 对比\n"
                    f"（检测到本 Job 的 Matrix/Code Target Ref 为 `{target_ref}`，"
                    f"而 Workflow Branch 为 `{workflow_branch or 'unknown'}`。"
                    "为避免误把 main workflow 的 PR/commit 当作根因，已禁止使用 "
                    f"`{last_success.head_sha[:7]}` -> `{current_run.head_sha[:7]}` 的 workflow SHA 对比。"
                    "当前或上次成功 job log 中缺少可抽取的被测代码 commit，需先补齐日志/checkout SHA 后再建立代码回归区间。）"
                )

            base_sha = last_tested_commit
            head_sha = tested_commit
            boundary_label = f"Tested Code `{target_ref}`"

        if base_sha == head_sha:
            return f"\n### Commit 对比\n（当前失败 run 与上次成功 run 的 {boundary_label} SHA 相同，无代码变更）"

        lines = []
        lines.append(f"\n### Commit 对比（同名 Job 上次成功 {boundary_label} `{base_sha[:7]}` -> 当前失败/Bad Head `{head_sha[:7]}`）\n")
        lines.append(
            "**边界语义**: 当前失败 SHA 只是已知 bad/head 边界，不等于致错提交。"
            "真正 culprit 必须从 last-good..bad 区间内逐个提交验证；证据不足时只能标记为候选。\n"
        )
        if target_diff_required:
            lines.append(
                f"**注意**: 本区间使用 job log 中实际 checkout 的 `{target_ref}` 被测代码 SHA，"
                "不是 GitHub Actions workflow 的 main head SHA。\n"
            )

        try:
            from app.services.github_client import GitHubClient
            github_token = settings.GITHUB_TOKEN
            if not github_token:
                lines.append("（GitHub Token 未配置，无法获取 commit 对比详情）")
                return "\n".join(lines)

            client = GitHubClient(token=github_token, owner=settings.GITHUB_OWNER, repo=settings.GITHUB_REPO)
            compare = await client.get_compare_commits(base_sha, head_sha)

            commits = compare.get("commits", [])
            if commits:
                lines.append(f"共 {len(commits)} 个 commit 被合入：\n")
                for c in commits[:15]:
                    sha_short = c.get("sha", "")[:7]
                    message = c.get("commit", {}).get("message", "").split("\n")[0]
                    lines.append(f"- `{sha_short}` {message}")

                if len(commits) > 15:
                    lines.append(f"- ... 共 {len(commits)} 个 commit（仅显示前 15 个）")

                required_candidates = self._rank_required_regression_candidates(
                    job,
                    commits,
                    failure_context=failure_context,
                )
                if required_candidates:
                    lines.append("\n### 必须审查的回归区间提交（不是默认候选根因）\n")
                    lines.append(
                        "以下提交与当前 Job/失败日志关键词存在可审查相关性。"
                        "它们不是默认候选根因；agent 必须给出处置：promote_to_candidate 或 dismiss_with_reason。"
                        "只有存在日志事实、源码调用链、配置入口或测试影响证据时，才允许提升为 candidate；"
                        "否则应作为已审查但无支持证据的排除项，不应出现在“主要/其他候选根因”中。\n"
                    )
                    for item in required_candidates:
                        lines.append(
                            f"- `{item['sha'][:7]}` PR #{item.get('pr') or 'unknown'} "
                            f"score={item['score']} matched={', '.join(item['matched_keywords'])}: {item['title']}"
                        )
                    lines.append("\n```json")
                    lines.append(json.dumps(
                        {"required_regression_candidates": required_candidates},
                        ensure_ascii=False,
                    ))
                    lines.append("```")
            else:
                lines.append("（无中间 commit 信息）")

            files = compare.get("files", [])
            if files:
                changed_paths = [f.get("filename", "") for f in files[:10]]
                lines.append(f"\n变更文件（共 {len(files)} 个，显示前 10 个）：")
                for p in changed_paths:
                    lines.append(f"- `{p}`")

        except Exception as e:
            logger.warning(f"Failed to fetch commit comparison: {e}")
            lines.append(f"（获取 commit 对比失败: {e}）")

        return "\n".join(lines)

    @staticmethod
    def _extract_failure_context_for_candidate_ranking(log_path: str | None) -> str:
        if not log_path:
            return ""
        try:
            text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
        patterns = (
            "error", "exception", "failed", "failure", "traceback", "eaddrinuse",
            "timeout", "accuracy", "assert", "insufficient", "pending",
            "init_distributed_environment", "port", "socket",
        )
        lines = [
            line[:500]
            for line in text.splitlines()
            if any(pattern in line.lower() for pattern in patterns)
        ]
        return "\n".join(lines[:200] + lines[-200:])[:60000]

    @staticmethod
    def _rank_required_regression_candidates(job: CIJob, commits: list[dict], failure_context: str = "") -> list[dict]:
        """Deprecated: never pre-promote regression-window commits as candidates.

        A good/bad regression window is evidence material, not a candidate list.
        Keyword/title matching is allowed only as a retrieval hint inside the
        investigating agent.  It is not strong enough to create required
        candidates or force report coverage, because relevance must be proven by
        a log symptom -> runtime entry/config -> source path -> diff chain.
        """
        return []

        job_text = f"{job.workflow_name} {job.job_name} {job.hardware or ''} {job.runner_name or ''}".lower()
        failure_text = (failure_context or "").lower()
        dynamic_keywords = {
            token
            for token in re.split(r"[^a-z0-9]+", job_text)
            if len(token) >= 3
            and token not in {
                "linux", "node", "main", "run", "job", "yaml", "nightly",
                "release", "releases", "workflow", "single", "double",
            }
            and not re.fullmatch(r"v?\d+(?:\.\d+)*", token)
        }
        infra_failure = any(marker in failure_text for marker in (
            "eaddrinuse", "failedscheduling", "insufficient huawei.com",
            "init_distributed_environment", "server socket", "port:",
            "address already in use", "connection timed out", "pending",
        ))
        accuracy_failure = any(marker in failure_text for marker in (
            "accuracy", "acc", "threshold", "baseline", "assert", "expected",
            "verification failed", "score",
        ))
        runtime_failure = any(marker in failure_text for marker in (
            "traceback", "runtimeerror", "valueerror", "cuda", "npu", "acl",
            "attention", "kv", "decode", "prefill", "model_runner",
        ))
        if infra_failure and not accuracy_failure:
            domain_keywords = {
                "distributed", "init", "worker", "multiproc", "executor", "port",
                "socket", "network", "host", "rank", "parallel", "process",
                "env", "runner", "k8s", "pod", "schedule", "resource",
            }
            strong_required_keywords = {
                "distributed", "init", "multiproc", "executor", "port",
                "socket", "network", "rank", "parallel", "process",
                "runner", "k8s", "pod", "schedule", "resource",
            }
            excluded_runtime_keywords = {
                "attention", "attn", "sfa", "dcp", "pcp", "prefill", "decode",
                "spec", "mtp", "kv", "gather", "cache", "rope", "query",
                "quant", "fused", "infer", "accuracy",
            }
        elif accuracy_failure or runtime_failure:
            domain_keywords = {
                "accuracy", "attention", "attn", "sfa", "dcp", "pcp", "prefill",
                "decode", "spec", "mtp", "longseq", "kv", "gather", "cache",
                "rope", "query", "lens", "seq", "rank", "tp", "ep", "moe",
                "qwen", "w8a8", "quant", "acl", "graph", "fused", "infer",
            }
            strong_required_keywords = set()
            excluded_runtime_keywords = set()
        else:
            domain_keywords = {
                "worker", "distributed", "init", "model", "runner", "config",
                "test", "workflow", "env",
            }
            strong_required_keywords = set()
            excluded_runtime_keywords = set()
        keywords = dynamic_keywords | domain_keywords
        ranked: list[dict] = []
        for c in commits:
            sha = str(c.get("sha") or "")
            title = str(c.get("commit", {}).get("message", "")).split("\n")[0]
            title_lower = title.lower()
            title_tokens = set(re.split(r"[^a-z0-9]+", title_lower))
            if excluded_runtime_keywords and (title_tokens & excluded_runtime_keywords):
                # For early infra/init failures, runtime-path PRs are not
                # forced into the review list solely because their titles match
                # broad model-domain keywords such as KV/Attention.
                continue
            matched = sorted({kw for kw in keywords if kw and kw in title_tokens})
            if not matched:
                continue
            if strong_required_keywords and not (set(matched) & strong_required_keywords):
                continue
            pr_match = re.search(r"\(#(\d{4,6})\)", title)
            score = len(matched)
            if pr_match:
                score += 1
            if any(kw in matched for kw in ("attention", "attn", "sfa", "dcp", "prefill", "decode", "spec", "mtp", "kv", "gather", "accuracy", "distributed", "worker", "multiproc", "port", "socket")):
                score += 2
            # Generic docs/test-only commits are useful context but should not
            # crowd out runtime candidates unless other relevant terms match.
            if re.search(r"\b(doc|docs|readme|typo)\b", title_lower) and score < 5:
                continue
            if score < 3:
                continue
            ranked.append({
                "sha": sha,
                "pr": pr_match.group(1) if pr_match else "",
                "title": title[:300],
                "score": score,
                "matched_keywords": matched[:12],
            })
        ranked.sort(key=lambda item: (-int(item["score"]), item["title"]))
        return ranked[:12]

    @staticmethod
    def compute_failure_fingerprint(job: CIJob) -> str:
        try:
            steps = json.loads(job.steps_data) if job.steps_data else []
        except (json.JSONDecodeError, TypeError):
            steps = []

        failed_steps = []
        for step in steps:
            if step.get("conclusion") in ("failure", "timed_out", "startup_failure"):
                failed_steps.append({"name": step.get("name", ""), "conclusion": step.get("conclusion", "")})

        if not failed_steps:
            fingerprint_data = json.dumps({"conclusion": job.conclusion or ""}, sort_keys=True)
        else:
            fingerprint_data = json.dumps({"failed_steps": failed_steps}, sort_keys=True)

        return hashlib.md5(fingerprint_data.encode()).hexdigest()

    @staticmethod
    def _detect_api_error(raw: str) -> str | None:
        """妫€娴?CLI 杈撳嚭鏄惁瀹炰负涓婃父 LLM/API 閿欒锛堣€岄潪鍒嗘瀽缁撴灉锛夈€?

        Claude Code CLI 鍦ㄤ笂娓歌繑鍥為敊璇椂锛屼細鎶婇敊璇俊鎭綔涓?content 杩斿洖
        锛堝 "API Error: 400 /chat/completions: Invalid model name ..."锛夈€?
        姝ょ被鍐呭浼氳 parse_llm_response 鍏滃簳涓?problem_category="鍏朵粬"锛?
        浠庤€屾妸澶辫触璇爣涓?completed銆傝繖閲屾彁鍓嶈瘑鍒苟杩斿洖閿欒鎻忚堪锛?
        鐢变笂灞?except 鏍囪 analysis_status="failed" 骞跺啓鍏?error_message銆?
        """
        text = raw.strip()
        if not text:
            return None
        low = text.lower()
        signatures = (
            "api error",
            "invalid model name",
            "model not found",
            "model is not supported",
            "call `/v1/models`",
        )
        # 浠呭綋鍐呭杈冪煭锛堢枒浼肩函閿欒娑堟伅锛夋椂鍒ゅ畾锛岄伩鍏嶈浼ゅ惈 error 瀛楁牱鐨勬甯稿垎鏋?
        if len(text) < 400:
            for sig in signatures:
                if sig in low:
                    return text[:300]
        return None

    @staticmethod
    def _extract_json_block(text: str) -> str | None:
        """Extract a JSON code block or the last complete JSON object."""
        # 1. ```json ... ``` 浠ｇ爜鍧?
        m = re.search(r'```json\s*\n?(.*?)```', text, re.DOTALL)
        if m:
            candidate = m.group(1).strip()
            if candidate.startswith('{'):
                return candidate
        # 2. Decode every object and prefer the last complete report-summary
        # object. Reverse brace matching used to return a nested child object.
        decoder = json.JSONDecoder()
        objects: list[tuple[str, dict]] = []
        for start, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, consumed = decoder.raw_decode(text[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                objects.append((text[start:start + consumed], value))
        required = {
            "problem_category",
            "root_cause_summary",
            "improvement_measures_summary",
        }
        for raw_object, value in reversed(objects):
            if required.issubset(value):
                return raw_object
        if objects:
            return objects[-1][0]
        return None

    @staticmethod
    def _extract_report_summary(text: str) -> dict:
        """Return the final structured report summary, or an empty mapping."""
        json_text = FailureAnalysisService._extract_json_block(text)
        if not json_text:
            return {}
        try:
            value = json.loads(json_text)
        except (json.JSONDecodeError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _deep_search_json(data: dict, key: str, default: str = "") -> str:
        """Recursively search a nested JSON object for a string field."""
        if key in data and isinstance(data[key], str) and data[key]:
            return data[key]
        for v in data.values():
            if isinstance(v, dict):
                result = FailureAnalysisService._deep_search_json(v, key, default)
                if result != default:
                    return result
        return default

    @staticmethod
    def _preserve_uncertainty_in_summary(raw: str, summary: str) -> str:
        """Prevent an evidence gap in the report becoming a certain DB summary."""
        raw_lower = raw.lower()
        uncertainty_markers = (
            "evidence gap",
            "needs verification",
            "[assumption",
            "证据缺口",
            "需要验证",
            "未验证",
        )
        summary_lower = summary.lower()
        qualified_markers = (
            "candidate",
            "most likely",
            "inferred",
            "unverified",
            "候选",
            "推断",
            "可能",
            "未验证",
        )
        if (
            summary
            and any(marker in raw_lower for marker in uncertainty_markers)
            and not any(marker in summary_lower for marker in qualified_markers)
        ):
            return f"候选（存在未验证证据缺口）: {summary}"
        return summary

    @staticmethod
    def parse_llm_response(raw: str) -> dict:
        json_str = FailureAnalysisService._extract_json_block(raw)

        if json_str:
            try:
                data = json.loads(json_str)
                if not isinstance(data, dict):
                    data = {}
                # 鍏堟壘椤跺眰锛屾壘涓嶅埌灏遍€掑綊鎼滅储宓屽缁撴瀯
                category = FailureAnalysisService._deep_search_json(data, "problem_category", "其他")
                if category not in VALID_CATEGORIES:
                    for cat in VALID_CATEGORIES:
                        if cat in category:
                            category = cat
                            break
                    else:
                        category = "其他"
                root_cause = FailureAnalysisService._deep_search_json(data, "root_cause_summary", "")
                root_cause = FailureAnalysisService._preserve_uncertainty_in_summary(raw, root_cause)
                measures = FailureAnalysisService._deep_search_json(data, "improvement_measures_summary", "")
                return {
                    "problem_category": category,
                    "root_cause_summary": root_cause or "解析成功但摘要缺失",
                    "improvement_measures_summary": measures or "解析成功但措施缺失",
                    "full_report": raw,
                }
            except json.JSONDecodeError:
                pass

        category = None
        cause = None
        measures = None

        cat_match = re.search(r'"problem_category"\s*:\s*"([^"]+)"', raw)
        if cat_match:
            category = cat_match.group(1)
        cause_match = re.search(r'"root_cause_summary"\s*:\s*"([^"]+)"', raw)
        if cause_match:
            cause = cause_match.group(1)
        measures_match = re.search(r'"improvement_measures_summary"\s*:\s*"([^"]+)"', raw)
        if measures_match:
            measures = measures_match.group(1)

        if category not in VALID_CATEGORIES:
            for cat, keywords in CATEGORY_KEYWORDS.items():
                if any(kw in raw.lower() for kw in keywords):
                    category = cat
                    break
            if category not in VALID_CATEGORIES:
                category = "其他"

        # JSON 鍧楃己澶辨椂锛屼粠鎶ュ憡姝ｆ枃鎻愬彇鎽樿
        if not cause:
            # 灏濊瘯鍖归厤涓枃鏍煎紡锛?*鏍瑰洜鎽樿**锛歺xx 鎴?鏍瑰洜: xxx
            cause_match = re.search(r'(?:\*\*)?鏍瑰洜(?:鎽樿)?(?:\*\*)?\s*[:锛歖\s*(.+?)(?:\n|$)', raw)
            if not cause_match:
                cause_match = re.search(r'(?:\*\*)?Root Cause(?:\*\*)?\s*[:锛歖\s*(.+?)(?:\n|$)', raw)
            if cause_match:
                cause = cause_match.group(1).strip()[:200]
        if not measures:
            measures_match = re.search(r'(?:\*\*)?鏀硅繘(?:寤鸿|鎺柦)(?:鎽樿)?(?:\*\*)?\s*[:锛歖\s*(.+?)(?:\n|$)', raw)
            if not measures_match:
                measures_match = re.search(r'(?:\*\*)?鏀硅繘鎺柦(?:\*\*)?\s*[:锛歖\s*(.+?)(?:\n|$)', raw)
            if measures_match:
                measures = measures_match.group(1).strip()[:200]

        cause = FailureAnalysisService._preserve_uncertainty_in_summary(raw, cause or "")

        return {
            "problem_category": category or "其他",
            "root_cause_summary": cause or "分析失败，请查看完整报告",
            "improvement_measures_summary": measures or "分析失败，请查看完整报告",
            "full_report": raw,
        }

    @staticmethod
    def _looks_completed(analysis: JobFailureAnalysis | None) -> bool:
        if not analysis:
            return False
        if analysis.analysis_status not in ("analyzing", "failed"):
            return False
        if analysis.analysis_phase != "completed":
            return False
        return bool(
            analysis.report_file_path
            or analysis.share_token
            or analysis.root_cause_summary
            or analysis.improvement_measures_summary
        )

    async def _normalize_completed_status(
        self,
        analyses: JobFailureAnalysis | list[JobFailureAnalysis] | None,
        db: AsyncSession,
    ) -> bool:
        if analyses is None:
            return False
        items = analyses if isinstance(analyses, list) else [analyses]
        changed = False
        for analysis in items:
            if self._looks_completed(analysis):
                analysis.analysis_status = "completed"
                analysis.error_message = None
                changed = True
        if changed:
            await db.commit()
        return changed

    async def get_analysis(self, analysis_id: int, db: AsyncSession):
        stmt = select(JobFailureAnalysis).where(JobFailureAnalysis.id == analysis_id)
        result = await db.execute(stmt)
        analysis = result.scalar_one_or_none()
        if await self._normalize_completed_status(analysis, db):
            await db.refresh(analysis)
        return analysis

    async def get_analysis_by_job_id(self, job_id: int, db: AsyncSession):
        stmt = select(JobFailureAnalysis).where(JobFailureAnalysis.job_id == job_id)
        result = await db.execute(stmt)
        analysis = result.scalar_one_or_none()
        if await self._normalize_completed_status(analysis, db):
            await db.refresh(analysis)
        return analysis

    async def list_analyses(self, filters: Optional[dict] = None, db: AsyncSession = None):
        stmt = select(JobFailureAnalysis)
        if filters:
            if filters.get("problem_category"):
                stmt = stmt.where(JobFailureAnalysis.problem_category == filters["problem_category"])
            if filters.get("analysis_status"):
                stmt = stmt.where(JobFailureAnalysis.analysis_status == filters["analysis_status"])
            if filters.get("workflow_name"):
                stmt = stmt.where(JobFailureAnalysis.workflow_name == filters["workflow_name"])
            if filters.get("days_back"):
                cutoff = datetime.now(UTC) - timedelta(days=filters["days_back"])
                stmt = stmt.where(JobFailureAnalysis.failure_date >= cutoff)
        stmt = stmt.order_by(JobFailureAnalysis.failure_date.desc())
        result = await db.execute(stmt)
        items = result.scalars().all()
        if await self._normalize_completed_status(items, db):
            for item in items:
                await db.refresh(item)
        if filters and filters.get("analysis_status"):
            items = [
                item for item in items
                if item.analysis_status == filters["analysis_status"]
            ]
        return {"total": len(items), "items": items}

    async def _get_ci_result(self, db: AsyncSession, run_id: int):
        """Get CIResult including branch and head_sha."""
        stmt = select(CIResult).where(CIResult.run_id == run_id).limit(1)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _generate_pdf_async(self, analysis_id: int, md_content: str, workflow: str, job_name: str, job_id: int):
        """Generate PDF asynchronously and update DB when done."""
        try:
            from app.db.base import SessionLocal as SL
            meta = {}
            async with SL() as db:
                from sqlalchemy import select as sa_sel
                r = await db.execute(sa_sel(JobFailureAnalysis).where(JobFailureAnalysis.id == analysis_id))
                a = r.scalar_one_or_none()
                if a:
                    meta = {
                        "category": a.problem_category or "-",
                        "status": "已完成" if a.analysis_status == "completed" else a.analysis_status,
                        "summary": a.root_cause_summary or "-",
                        "measures": a.improvement_measures_summary or "-",
                        "provider": a.llm_provider or "",
                        "model": a.llm_model or "",
                        "duration": a.generation_time_seconds,
                    }
            pdf_path = await self._generate_pdf(md_content, workflow, job_name, job_id, metadata=meta)
            from app.db.base import SessionLocal
            async with SessionLocal() as db:
                from sqlalchemy import update
                await db.execute(
                    update(JobFailureAnalysis)
                    .where(JobFailureAnalysis.id == analysis_id)
                    .values(pdf_file_path=pdf_path)
                )
                await db.commit()
        except Exception as e:
            logger.warning("Async PDF generation failed: %s", e)

    async def _generate_pdf(self, md_content: str, workflow: str, job_name: str, job_id: int,
                            metadata: dict | None = None) -> str | None:
        """Generate a PDF file from a markdown report and return its path."""
        import html as html_lib
        from pathlib import Path
        from weasyprint import HTML

        try:
            import markdown
            rendered_markdown = markdown.markdown(
                md_content, extensions=['tables', 'fenced_code']
            )
        except ImportError:
            logger.warning("markdown package unavailable; using plain-text PDF fallback")
            rendered_markdown = "<pre>" + html_lib.escape(md_content) + "</pre>"

        # 鏋勫缓 metadata 琛?
        meta_html = ""
        if metadata:
            meta = metadata
            cat = meta.get("category", "-")
            status = meta.get("status", "-")
            summary = meta.get("summary", "-")
            measures = meta.get("measures", "-")
            provider = meta.get("provider", "")
            model = meta.get("model", "")
            duration = meta.get("duration")
            llm_row = f'<tr><td style="font-weight:bold;">LLM</td><td>{provider}/{model}</td><td style="font-weight:bold;">耗时</td><td>{duration:.1f}s</td></tr>' if provider else ""
            meta_html = f"""
<div style="margin-bottom: 20px; border: 1px solid #d9d9d9; border-radius: 4px; padding: 12px;">
<h2 style="margin-top:0; font-size: 16px;">分析报告摘要</h2>
<table>
<tr><td style="width:80px; font-weight:bold;">分类</td><td>{cat}</td><td style="width:80px; font-weight:bold;">状态</td><td>{status}</td></tr>
<tr><td style="font-weight:bold;">根因摘要</td><td colspan="3">{summary}</td></tr>
<tr><td style="font-weight:bold;">改进建议</td><td colspan="3">{measures}</td></tr>
{llm_row}
</table>
</div>
"""

        html = (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<style>'
            '@page { size: A4; margin: 15mm; }'
            'body { font-family: "Noto Sans CJK SC", "Segoe UI", Arial, sans-serif; max-width: 100%; margin: 0 auto; color: #333; line-height: 1.6; font-size: 12px; }'
            'h1 { border-bottom: 2px solid #1890ff; padding-bottom: 8px; font-size: 18px; }'
            'h2 { margin-top: 24px; color: #1890ff; font-size: 15px; page-break-before: auto; }'
            'h3 { page-break-after: avoid; }'
            'table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 11px; page-break-inside: avoid; }'
            'th, td { border: 1px solid #d9d9d9; padding: 6px 8px; text-align: left; word-break: break-all; }'
            'th { background: #f5f5f5; }'
            'pre { background: #f5f5f5; padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 10px; white-space: pre-wrap; word-wrap: break-word; max-width: 100%; }'
            'code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 10px; }'
            'img { max-width: 100%; }'
            '</style></head><body>'
            + meta_html
            + rendered_markdown
            + '</body></html>'
        )

        pdf_dir = self._data_root() / "failure-analysis" / workflow
        pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = pdf_dir / f"{job_id}.pdf"
        HTML(string=html).write_pdf(target=str(pdf_path))
        logger.info("PDF generated: %s", pdf_path)
        return str(pdf_path)

    async def _download_all_logs(self, job: CIJob) -> dict[str, str | None]:
        """Download available logs to local files and return their paths."""
        import aiohttp
        from pathlib import Path

        request_timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)

        log_dir = self._data_root() / "failure-analysis" / job.workflow_name
        log_dir.mkdir(parents=True, exist_ok=True)
        headers = {
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }

        result = {"job_log": None, "run_log_zip": None, "artifacts_dir": None, "jobs_list": None}

        # 1. Job log
        job_log_path = log_dir / f"{job.job_id}.log"
        if not job_log_path.exists():
            job_url = f"https://api.github.com/repos/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/jobs/{job.job_id}/logs"
            try:
                async with aiohttp.ClientSession(timeout=request_timeout) as session:
                    async with session.get(job_url, headers=headers) as resp:
                        if resp.status == 200:
                            job_log_path.write_bytes(await resp.read())
            except Exception as e:
                logger.warning("Failed to fetch job log: %s", e)
        if job_log_path.exists():
            result["job_log"] = str(job_log_path)

        # 2. Run 鍏ㄩ儴鏃ュ織 ZIP
        run_zip_path = log_dir / f"run_{job.run_id}_logs.zip"
        if not run_zip_path.exists():
            run_url = f"https://api.github.com/repos/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/runs/{job.run_id}/logs"
            try:
                async with aiohttp.ClientSession(timeout=request_timeout) as session:
                    async with session.get(run_url, headers=headers) as resp:
                        if resp.status == 200:
                            run_zip_path.write_bytes(await resp.read())
            except Exception as e:
                logger.warning("Failed to fetch run logs ZIP: %s", e)
        if run_zip_path.exists():
            result["run_log_zip"] = str(run_zip_path)

        # 3. Artifacts 鈥?涓嬭浇鍚庤嚜鍔ㄨВ鍘?
        artifacts_dir = log_dir / f"artifacts_{job.run_id}"
        artifacts_extracted_dir = artifacts_dir / "extracted"
        has_downloaded_artifacts = artifacts_dir.exists() and any(
            child.name != "extracted" for child in artifacts_dir.iterdir()
        )
        artifacts_extracted_dir.mkdir(parents=True, exist_ok=True)
        if not has_downloaded_artifacts:
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            art_url = f"https://api.github.com/repos/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/runs/{job.run_id}/artifacts"
            try:
                async with aiohttp.ClientSession(timeout=request_timeout) as session:
                    async with session.get(art_url, headers=headers) as resp:
                        if resp.status == 200:
                            art_data = await resp.json()
                            for art in art_data.get("artifacts", []):
                                art_path = artifacts_dir / f"{art['id']}_{art['name']}.zip"
                                if not art_path.exists():
                                    dl_url = art["archive_download_url"]
                                    async with session.get(dl_url, headers=headers) as dl_resp:
                                        if dl_resp.status == 200:
                                            art_path.write_bytes(await dl_resp.read())
                                # 鑷姩瑙ｅ帇
                                art_extract_dir = artifacts_extracted_dir / art["name"]
                                if not art_extract_dir.exists() and art_path.exists():
                                    art_extract_dir.mkdir(parents=True, exist_ok=True)
                                    try:
                                        import zipfile
                                        with zipfile.ZipFile(art_path, 'r') as zf:
                                            zf.extractall(art_extract_dir)
                                    except Exception:
                                        pass
            except Exception as e:
                logger.warning("Failed to fetch artifacts: %s", e)
        if artifacts_extracted_dir.exists() and any(artifacts_extracted_dir.iterdir()):
            result["artifacts_dir"] = str(artifacts_extracted_dir)
        elif artifacts_dir.exists() and any(artifacts_dir.iterdir()):
            result["artifacts_dir"] = str(artifacts_dir)

        # 4. Run jobs 鍒楄〃锛堝鑺傜偣鍦烘櫙闇€瑕侊級
        import json
        jobs_path = log_dir / f"run_{job.run_id}_jobs.json"
        if not jobs_path.exists():
            jobs_url = f"https://api.github.com/repos/{settings.GITHUB_OWNER}/{settings.GITHUB_REPO}/actions/runs/{job.run_id}/jobs?per_page=100"
            try:
                async with aiohttp.ClientSession(timeout=request_timeout) as session:
                    async with session.get(jobs_url, headers=headers) as resp:
                        if resp.status == 200:
                            jobs_path.write_text(json.dumps(await resp.json(), ensure_ascii=False, indent=2))
            except Exception as e:
                logger.warning("Failed to fetch jobs list: %s", e)
        if jobs_path.exists():
            result["jobs_list"] = str(jobs_path)

        downloaded = sum(1 for v in result.values() if v)
        logger.info("Pre-fetched %d log sources for job %s", downloaded, job.job_id)
        return result

