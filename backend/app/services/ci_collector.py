"""
CI 数据采集服务
从 GitHub Actions API 采集 CI 运行数据并保存到数据库
"""
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CIJob, CIResult, WorkflowConfig
from app.services.github_client import GitHubAPIError, GitHubClient, GitHubRateLimitError
from app.services.sync_progress import get_sync_progress

logger = logging.getLogger(__name__)


class CICollector:
    """
    CI 数据采集服务

    功能：
    - 从 GitHub API 采集 workflow runs 数据
    - 识别硬件信息（A2/A3）
    - 保存到数据库
    """

    def __init__(
        self,
        github_client: GitHubClient,
        db_session: AsyncSession,
    ):
        """
        初始化 CI 采集器

        Args:
            github_client: GitHub API 客户端
            db_session: 数据库会话
        """
        self.github = github_client
        self.db = db_session

    async def collect_workflow_runs(
        self,
        workflow_files: list[str] | None = None,
        days_back: int = 7,
        max_runs_per_workflow: int = 100,
        force_full_refresh: bool = False,
    ) -> int:
        """
        采集 workflow 运行数据

        Args:
            workflow_files: workflow 文件名列表，None 则从数据库获取启用的配置
            days_back: 获取多少天的数据
            max_runs_per_workflow: 每个 workflow 最多获取多少条记录
            force_full_refresh: 是否强制全量覆盖刷新（忽略已有记录）

        Returns:
            新增或更新的记录数
        """
        # 如果没有指定 workflow 列表，从数据库获取启用的配置
        if workflow_files is None:
            stmt = select(WorkflowConfig).where(WorkflowConfig.enabled == True)
            result = await self.db.execute(stmt)
            workflow_configs = result.scalars().all()
            workflow_files = [
                (config.workflow_file, config.hardware, getattr(config, 'event', 'schedule') or None, getattr(config, 'actor', None))
                for config in workflow_configs
            ]
            logger.info(f"Loaded {len(workflow_files)} enabled workflows from database")
        else:
            # 兼容旧格式：转换为 (workflow_file, hardware, event, actor) 元组列表
            workflow_files = [(wf, "A2", "schedule", None) for wf in workflow_files]

        # 初始化进度跟踪器
        progress = get_sync_progress()
        # 如果还没有开始（API 层可能已经启动了），则启动
        if progress.status == "idle":
            progress.total_workflows = len(workflow_files)
            progress.start()
        else:
            # 更新 workflow 数量
            progress.total_workflows = len(workflow_files)

        since = datetime.now(UTC) - timedelta(days=days_back)
        total_collected = 0

        logger.info(f"Starting CI data collection since {since.isoformat()}, force_full_refresh={force_full_refresh}")

        for wf_item in workflow_files:
            workflow_file, hardware = wf_item[0], wf_item[1]
            event_filter = wf_item[2] if len(wf_item) > 2 else "schedule"
            actor_filter = wf_item[3] if len(wf_item) > 3 else None
            try:
                # 更新当前正在处理的 workflow
                progress.current_workflow = workflow_file
                progress.workflow_details[workflow_file] = {
                    "status": "running",
                    "updated_at": datetime.now(UTC).isoformat(),
                }

                collected = await self._collect_single_workflow(
                    workflow_file=workflow_file,
                    since=since,
                    progress=progress,
                    max_runs=max_runs_per_workflow,
                    hardware=hardware,
                    force_full_refresh=force_full_refresh,
                    event=event_filter,
                    actor=actor_filter,
                )
                total_collected += collected

                # 更新进度
                progress.update_workflow_progress(workflow_file, collected, "completed")
                logger.info(f"Collected {collected} runs for {workflow_file}")

            except GitHubRateLimitError as e:
                logger.error(f"Rate limit exceeded while fetching {workflow_file}: {e}")
                progress.update_workflow_progress(workflow_file, 0, "failed")
                try:
                    await self.db.rollback()
                except Exception as rollback_error:
                    logger.error(f"Failed to rollback database transaction: {rollback_error}")
                break  # 速率限制，停止采集
            except GitHubAPIError as e:
                logger.error(f"Failed to fetch workflow {workflow_file}: {e}")
                progress.update_workflow_progress(workflow_file, 0, "failed")
                try:
                    await self.db.rollback()
                except Exception as rollback_error:
                    logger.error(f"Failed to rollback database transaction: {rollback_error}")
                continue  # 继续尝试其他 workflow
            except Exception as e:
                logger.error(f"Unexpected error processing {workflow_file}: {e}", exc_info=True)
                progress.update_workflow_progress(workflow_file, 0, "failed")
                try:
                    await self.db.rollback()
                except Exception as rollback_error:
                    logger.error(f"Failed to rollback database transaction: {rollback_error}")
                continue

        # 完成同步
        progress.complete()
        logger.info(f"CI data collection completed. Total: {total_collected} runs")
        return total_collected

    async def _collect_single_workflow(
        self,
        workflow_file: str,
        since: datetime,
        progress: Any,
        max_runs: int = 100,
        hardware: str = "A2",
        force_full_refresh: bool = False,
        event: str | None = None,
        actor: str | None = None,
    ) -> int:
        """
        采集单个 workflow 的运行数据

        Args:
            workflow_file: workflow 文件名
            since: 起始时间
            progress: 进度跟踪器
            max_runs: 最多获取多少条记录
            hardware: 硬件类型
            force_full_refresh: 是否强制全量覆盖刷新（忽略已有记录）
            event: 事件类型过滤（None=不过滤）
            actor: 触发人过滤（None=不过滤）

        Returns:
            新增或更新的记录数
        """
        collected = 0
        updated_count = 0
        page = 1

        # 获取该 workflow 已同步的最新 run_id（用于增量同步）
        last_synced_run_id = await self._get_last_synced_run_id(workflow_file)
        if last_synced_run_id and not force_full_refresh:
            logger.info(f"Last synced run_id for {workflow_file}: {last_synced_run_id}, will use incremental sync")

        logger.info(f"Collecting workflow: {workflow_file}, since: {since.isoformat()}, force_full_refresh={force_full_refresh}")

        while True:
            try:
                # 获取一页数据，只获取 event: schedule 的 runs
                # 使用 created 参数进行时间过滤（无论增量还是全量模式）
                # 全量模式下也需要限制时间范围，避免获取过多历史数据
                since_date = since.strftime('%Y-%m-%d')
                created_filter = f">={since_date}"

                runs = await self.github.get_workflow_runs(
                    workflow_id_or_name=workflow_file,
                    event=event or None,  # 使用配置的 event，空=不过滤
                    per_page=min(max_runs, 100),
                    page=page,
                    created=created_filter,  # 使用 created 参数过滤
                )
            except Exception as e:
                logger.error(f"Failed to fetch workflow runs for {workflow_file} (page {page}): {e}")
                break

            # actor 客户端过滤（GitHub API 不支持 actor 参数）
            if actor and runs:
                runs = [r for r in runs if (r.get("actor") or {}).get("login") == actor]

            logger.info(f"Fetched {len(runs)} runs for {workflow_file} (page {page}, event={event or 'all'}, actor={actor or 'all'})")

            if not runs:
                logger.info(f"No runs found for {workflow_file} (event={event or 'all'}, actor={actor or 'all'})")
                break  # 没有更多数据

            # 处理每条记录
            for run in runs:
                created_at = self._parse_datetime(run.get("created_at"))
                run_id = run.get("id")

                # 检查时间范围
                if created_at and created_at < since:
                    logger.info(f"Run {run_id} is older than {since}, stopping collection for {workflow_file}")
                    # 提交已收集的数据
                    await self.db.commit()
                    return collected  # 超出时间范围，停止

                # 保存或更新记录
                updated = await self._save_ci_result(run, workflow_file, hardware)
                if updated:
                    collected += 1
                    updated_count += 1
                    # 实时更新已采集记录数
                    progress.update_collected_count(1)
                elif not force_full_refresh:
                    # 如果不是强制刷新，跳过已存在的记录
                    logger.debug(f"Run {run_id} already exists, skipped")
                else:
                    # 强制刷新模式下，即使已存在也要更新
                    logger.debug(f"Run {run_id} exists, but force refresh enabled")

                # 获取并保存 job 详细信息（无论 run 是否已存在，都尝试获取 jobs）
                try:
                    # 在强制刷新模式下，也强制更新 runner 信息
                    await self._collect_jobs(run_id, run, workflow_file, hardware, force_update_runner=force_full_refresh)
                except Exception as e:
                    logger.error(f"Failed to collect jobs for run {run_id}: {e}")

            # 检查是否达到最大数量
            if len(runs) < min(max_runs, 100):
                logger.info(f"Reached last page for {workflow_file}")
                break  # 已经是最后一页

            page += 1

            # 防止过度分页
            if page > 10:
                logger.warning(f"Reached max pagination for {workflow_file}")
                break

        # 提交最后的数据
        await self.db.commit()
        logger.info(f"Collection completed for {workflow_file}: {collected} new/updated, {updated_count} updated")
        return collected

    async def _save_ci_result(
        self,
        run: dict[str, Any],
        workflow_file: str,
        hardware: str,
    ) -> bool:
        """
        保存或更新 CI 结果
        
        Args:
            run: GitHub API 返回的 run 数据
            workflow_file: workflow 文件名
            
        Returns:
            是否新增或更新了记录
        """
        run_id = run.get("id")
        if not run_id:
            logger.warning("Run ID not found, skipping")
            return False

        # 检查是否已存在
        stmt = select(CIResult).where(CIResult.run_id == run_id)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # 更新现有记录
            return await self._update_ci_result(existing, run, hardware)
        else:
            # 创建新记录
            return await self._create_ci_result(run, workflow_file, hardware)

    async def _create_ci_result(
        self,
        run: dict[str, Any],
        workflow_file: str,
        hardware: str,
    ) -> bool:
        """创建新的 CI 结果记录"""
        try:
            # 从 WorkflowConfig 获取正确的 workflow_name
            from sqlalchemy import select
            from app.models import WorkflowConfig
            
            stmt = select(WorkflowConfig.workflow_name).where(
                WorkflowConfig.workflow_file == workflow_file
            )
            result = await self.db.execute(stmt)
            config_workflow_name = result.scalar_one_or_none()
            
            # 如果找不到配置，使用 GitHub API 返回的名称
            if config_workflow_name is None:
                logger.warning(f"WorkflowConfig not found for {workflow_file}, using GitHub name")
                config_workflow_name = run.get("name", workflow_file)
            
            ci_result = CIResult(
                workflow_name=config_workflow_name,
                run_id=run["id"],
                run_number=run.get("run_number"),
                status=run.get("status", "unknown"),
                conclusion=run.get("conclusion"),
                event=run.get("event"),
                branch=run.get("head_branch"),
                head_sha=run.get("head_sha"),
                started_at=self._parse_datetime(run.get("created_at")),
                completed_at=self._parse_datetime(run.get("updated_at")),
                duration_seconds=self._calculate_duration(run),
                hardware=hardware,
                data=json.dumps(run),
            )

            self.db.add(ci_result)
            # 不立即 commit，由上层统一 commit
            logger.debug(f"Created CI result for run {run['id']}")
            return True

        except Exception as e:
            logger.error(f"Failed to create CI result: {e}")
            return False

    async def _update_ci_result(
        self,
        existing: CIResult,
        run: dict[str, Any],
        hardware: str,
    ) -> bool:
        """更新现有 CI 结果记录"""
        try:
            # 只更新状态变化的字段
            needs_update = False

            new_status = run.get("status", "unknown")
            if existing.status != new_status:
                existing.status = new_status
                needs_update = True

            new_conclusion = run.get("conclusion")
            if existing.conclusion != new_conclusion:
                existing.conclusion = new_conclusion
                needs_update = True

            # 更新 run_number（如果之前为空）
            new_run_number = run.get("run_number")
            if existing.run_number is None and new_run_number is not None:
                existing.run_number = new_run_number
                needs_update = True

            # 更新 event（如果之前为空）
            new_event = run.get("event")
            if existing.event is None and new_event is not None:
                existing.event = new_event
                needs_update = True

            # 更新 branch（如果之前为空）
            new_branch = run.get("head_branch")
            if existing.branch is None and new_branch is not None:
                existing.branch = new_branch
                needs_update = True

            # 更新 head_sha（如果之前为空）
            new_head_sha = run.get("head_sha")
            if existing.head_sha is None and new_head_sha is not None:
                existing.head_sha = new_head_sha
                needs_update = True

            new_completed_at = self._parse_datetime(run.get("updated_at"))
            if existing.completed_at != new_completed_at and new_completed_at is not None:
                existing.completed_at = new_completed_at
                needs_update = True

            new_duration = self._calculate_duration(run)
            if existing.duration_seconds != new_duration and new_duration is not None:
                existing.duration_seconds = new_duration
                needs_update = True

            # 更新硬件信息（如果之前识别错误）
            if existing.hardware != hardware and hardware != "unknown":
                existing.hardware = hardware
                needs_update = True

            # 更新原始数据
            existing.data = json.dumps(run)
            needs_update = True

            if needs_update:
                # 不立即 commit，由上层统一 commit
                logger.debug(f"Updated CI result for run {run['id']}")

            return needs_update

        except Exception as e:
            logger.error(f"Failed to update CI result: {e}")
            return False

    def _calculate_duration(self, run: dict[str, Any]) -> int | None:
        """
        计算运行时长（秒）

        优先使用 GitHub 的 run_started_at / run_updated_at（实际执行窗口），
        回退到 created_at / updated_at。

        Args:
            run: workflow run 数据

        Returns:
            时长（秒），无法计算时返回 None
        """
        started_at = self._parse_datetime(run.get("run_started_at") or run.get("created_at"))
        completed_at = self._parse_datetime(run.get("run_updated_at") or run.get("updated_at"))

        if started_at and completed_at:
            return int((completed_at - started_at).total_seconds())

        return None

    def _parse_datetime(self, dt_string: str | None) -> datetime | None:
        """
        解析 ISO 8601 格式的日期时间字符串

        Args:
            dt_string: 日期时间字符串，如 "2024-03-24T10:00:00Z"

        Returns:
            datetime 对象，解析失败时返回 None
        """
        if not dt_string:
            return None

        try:
            # 处理 Z 后缀
            dt_string = dt_string.replace("Z", "+00:00")
            return datetime.fromisoformat(dt_string)
        except (ValueError, TypeError) as e:
            logger.warning(f"Failed to parse datetime '{dt_string}': {e}")
            return None

    async def _collect_jobs(
        self,
        run_id: int,
        run_data: dict[str, Any],
        workflow_file: str,
        hardware: str,
        force_update_runner: bool = False,
    ) -> int:
        """
        获取并保存 workflow run 的 job 详细信息

        Args:
            run_id: workflow run ID
            run_data: workflow run 数据
            workflow_file: workflow 文件名
            hardware: 硬件类型
            force_update_runner: 是否强制更新 runner 信息

        Returns:
            采集的 job 数量
        """
        try:
            logger.info(f"Fetching jobs for run {run_id}...")

            # 获取 job 列表
            jobs = await self.github.get_job_list(run_id)
            logger.info(f"GitHub API returned {len(jobs)} jobs for run {run_id}")

            if not jobs:
                logger.warning(f"No jobs found for run {run_id}")
                return 0

            saved_count = 0
            new_count = 0
            update_count = 0

            for job in jobs:
                job_id = job.get("id")
                if not job_id:
                    logger.warning(f"Job missing ID in run {run_id}")
                    continue

                # 检查是否已存在
                stmt = select(CIJob).where(CIJob.job_id == job_id)
                result = await self.db.execute(stmt)
                existing = result.scalar_one_or_none()

                if existing:
                    # 更新现有记录
                    updated = await self._update_ci_job(existing, job, workflow_file, hardware, force_update_runner)
                    if updated:
                        update_count += 1
                    saved_count += 1
                else:
                    # 创建新记录
                    created = await self._create_ci_job(job, run_id, workflow_file, hardware)
                    if created:
                        new_count += 1
                        saved_count += 1

                # 如果 job 失败且已完成，自动获取日志（已禁用，直接跳转到 GitHub 查看）
                # job_conclusion = job.get("conclusion")
                # job_status = job.get("status")
                # if job_status == "completed" and job_conclusion == "failure":
                #     try:
                #         logs = await self.github.get_job_logs(job_id)
                #         if logs:
                #             # 更新 job 记录，保存日志
                #             await self._save_job_logs(job_id, logs)
                #             failed_jobs_with_logs += 1
                #             logger.info(f"Auto-fetched logs for failed job {job_id}")
                #     except Exception as e:
                #         logger.error(f"Failed to fetch logs for job {job_id}: {e}")

            logger.info(f"Collected {saved_count} jobs for run {run_id} (new: {new_count}, updated: {update_count})")

            # 注意：不在这里 commit，由外层统一 commit
            return saved_count

        except Exception as e:
            logger.error(f"Failed to collect jobs for run {run_id}: {e}", exc_info=True)
            raise  # 抛出异常，由外层处理回滚

    async def _create_ci_job(
        self,
        job: dict[str, Any],
        run_id: int,
        workflow_file: str,
        hardware: str,
    ) -> bool:
        """创建新的 CI Job 记录"""
        try:
            # 提取 steps 信息
            steps = job.get("steps", [])
            steps_summary = []
            for step in steps:
                steps_summary.append({
                    "name": step.get("name", ""),
                    "status": step.get("status", ""),
                    "conclusion": step.get("conclusion"),
                    "number": step.get("number", 0),
                })

            # 提取 runner 标签（GitHub API 直接在 job 顶层返回 labels 字段）
            runner_labels = job.get("labels", [])
            if isinstance(runner_labels, list):
                # 标签可能是字典列表或字符串列表
                label_names = []
                for label in runner_labels:
                    if isinstance(label, dict):
                        label_names.append(label.get("name", ""))
                    else:
                        label_names.append(str(label))
                runner_labels = label_names

            ci_job = CIJob(
                job_id=job["id"],
                run_id=run_id,
                workflow_name=job.get("workflow_name", workflow_file),
                job_name=job.get("name", ""),
                status=job.get("status", "unknown"),
                conclusion=job.get("conclusion"),
                started_at=self._parse_datetime(job.get("started_at")),
                completed_at=self._parse_datetime(job.get("completed_at")),
                duration_seconds=self._calculate_job_duration(job),
                hardware=hardware,
                runner_name=job.get("runner_name"),  # GitHub API 直接返回 runner_name 字段
                runner_labels=json.dumps(runner_labels),
                steps_data=json.dumps(steps_summary),
                logs_url=f"https://api.github.com/repos/{self.github.owner}/{self.github.repo}/actions/jobs/{job['id']}/logs",
                data=json.dumps(job),
            )

            self.db.add(ci_job)
            logger.debug(f"Created CI job {job['id']} for run {run_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to create CI job: {e}")
            return False

    async def _update_ci_job(
        self,
        existing: CIJob,
        job: dict[str, Any],
        workflow_file: str,
        hardware: str,
        force_update_runner: bool = False,
    ) -> bool:
        """更新现有 CI Job 记录

        Args:
            existing: 现有的 CIJob 记录
            job: GitHub API 返回的 job 数据
            workflow_file: workflow 文件名
            hardware: 硬件类型
            force_update_runner: 是否强制更新 runner 信息
        """
        try:
            needs_update = False

            # 更新状态
            new_status = job.get("status", "unknown")
            if existing.status != new_status:
                existing.status = new_status
                needs_update = True

            new_conclusion = job.get("conclusion")
            if existing.conclusion != new_conclusion:
                existing.conclusion = new_conclusion
                needs_update = True

            # 更新时间
            new_completed_at = self._parse_datetime(job.get("completed_at"))
            if new_completed_at and existing.completed_at != new_completed_at:
                existing.completed_at = new_completed_at
                needs_update = True

                # 重新计算时长
                new_duration = self._calculate_job_duration(job)
                if new_duration and existing.duration_seconds != new_duration:
                    existing.duration_seconds = new_duration
                    needs_update = True

            # 更新 steps 信息
            steps = job.get("steps", [])
            if steps:
                steps_summary = []
                for step in steps:
                    steps_summary.append({
                        "name": step.get("name", ""),
                        "status": step.get("status", ""),
                        "conclusion": step.get("conclusion"),
                        "number": step.get("number", 0),
                    })
                existing.steps_data = json.dumps(steps_summary)
                needs_update = True

            # 更新 runner 信息（GitHub API 直接在 job 顶层返回 runner_name 和 labels 字段）
            new_runner_name = job.get("runner_name")
            if force_update_runner and new_runner_name:
                # 强制更新模式：总是更新 runner 信息
                if existing.runner_name != new_runner_name:
                    existing.runner_name = new_runner_name
                    needs_update = True
            elif new_runner_name and existing.runner_name != new_runner_name:
                # 普通模式：只在 runner 名称变化时更新
                existing.runner_name = new_runner_name
                needs_update = True

            new_runner_labels = job.get("labels", [])
            if isinstance(new_runner_labels, list):
                label_names = [
                    label.get("name", "") if isinstance(label, dict) else str(label)
                    for label in new_runner_labels
                ]
                new_runner_labels_str = json.dumps(label_names)
                if existing.runner_labels != new_runner_labels_str:
                    existing.runner_labels = new_runner_labels_str
                    needs_update = True

            # 更新原始数据
            existing.data = json.dumps(job)
            needs_update = True

            if needs_update:
                logger.debug(f"Updated CI job {job['id']}")

            return needs_update

        except Exception as e:
            logger.error(f"Failed to update CI job: {e}")
            return False

    def _calculate_job_duration(self, job: dict[str, Any]) -> int | None:
        """计算 job 运行时长（秒）"""
        started_at = self._parse_datetime(job.get("started_at"))
        completed_at = self._parse_datetime(job.get("completed_at"))

        if started_at and completed_at:
            return int((completed_at - started_at).total_seconds())

        return None

    async def _get_last_synced_run_id(self, workflow_file: str) -> int | None:
        try:
            stmt = select(WorkflowConfig.workflow_name).where(
                WorkflowConfig.workflow_file == workflow_file
            )
            config_result = await self.db.execute(stmt)
            workflow_name = config_result.scalar_one_or_none()

            if not workflow_name:
                logger.warning(f"WorkflowConfig not found for {workflow_file}, using workflow_file as name")
                workflow_name = workflow_file

            stmt = select(func.max(CIResult.run_id)).where(CIResult.workflow_name == workflow_name)
            result = await self.db.execute(stmt)
            max_run_id = result.scalar()
            return max_run_id if max_run_id else None
        except Exception as e:
            logger.warning(f"Failed to get last synced run_id for {workflow_file}: {e}")
            return None
