"""
模型报告同步服务
从 GitHub Actions artifacts 同步模型报告
"""
import fnmatch
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.clients.github_client import GitHubAuthenticationError, GitHubClient
from infrastructure.core.config import settings
from infrastructure.persistence.models import ModelConfig, ModelReport, ModelSyncConfig
from tooling.parsers.model_report_parser import ModelReportParser

logger = logging.getLogger(__name__)


class ModelSyncService:
    """模型报告同步服务"""

    def __init__(self, db: AsyncSession, github_client: GitHubClient):
        self.db = db
        self.github = github_client
        self.parser = ModelReportParser()
        self.owner = settings.GITHUB_OWNER
        self.repo = settings.GITHUB_REPO

    async def sync_all_enabled_configs(
        self,
        days_back: int = 3,
        runs_limit: int = 100
    ) -> tuple[int, int]:
        """
        同步所有启用的配置

        Args:
            days_back: 从多少天前开始采集
            runs_limit: 每个 workflow 最多获取最近 N 次 runs

        Returns:
            (total_configs, collected_count)
        """
        # 获取所有启用的同步配置
        stmt = select(ModelSyncConfig).where(ModelSyncConfig.enabled)
        result = await self.db.execute(stmt)
        configs = result.scalars().all()

        total_collected = 0
        for config in configs:
            try:
                collected = await self.sync_from_workflow(
                    config,
                    days_back=days_back,
                    runs_limit=runs_limit,
                )
                total_collected += collected
            except GitHubAuthenticationError:
                # An invalid credential is a task-level failure.  Do not turn
                # it into a successful zero-result sync, otherwise the UI
                # reports completed while silently dropping all model data.
                raise
            except Exception as e:
                logger.error(f"Failed to sync from workflow {config.workflow_name}: {e}")

        return len(configs), total_collected

    async def sync_from_workflow(
        self,
        config: ModelSyncConfig,
        days_back: int = 3,
        runs_limit: int = 100
    ) -> int:
        """
        从指定 workflow 同步报告

        Args:
            config: 同步配置
            days_back: 从多少天前开始采集
            runs_limit: 每个 workflow 最多获取最近 N 次 runs（使用全局配置）

        Returns:
            采集的报告数量
        """
        logger.info(f"Starting sync for workflow: {config.workflow_name}")

        try:
            # 获取最近的 workflow runs（数量使用全局配置，可指定分支）
            runs = await self.github.get_workflow_runs(
                config.workflow_file,
                branch=config.branch or "main",  # 默认 main 分支
                per_page=runs_limit,  # 使用全局配置
                days_back=days_back,  # 从多少天前开始采集
            )
        except GitHubAuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Failed to fetch workflow runs: {e}")
            return 0

        collected = 0

        for run in runs:
            run_id = run["id"]

            # 检查是否已存在该 run 的报告
            existing = await self._check_existing_report(run_id)
            if existing:
                logger.debug(f"Report for run {run_id} already exists, skipping")
                continue

            # 获取 artifacts
            try:
                artifacts = await self.github.list_artifacts(run_id)
            except GitHubAuthenticationError:
                raise
            except Exception as e:
                logger.warning(f"Failed to list artifacts for run {run_id}: {e}")
                continue

            # 匹配 artifacts
            matching_artifacts = self._match_artifacts(artifacts, config.artifacts_pattern)

            for artifact in matching_artifacts:
                try:
                    # 下载 artifact
                    artifact_content = await self.github.download_artifact(
                        self.owner,
                        self.repo,
                        artifact["id"]
                    )

                    # 解析并保存报告（传入 artifact name）
                    saved = await self._process_artifact(
                        artifact_content,
                        config,
                        run,
                        artifact.get("name", "")
                    )
                    if saved:
                        collected += 1

                except GitHubAuthenticationError:
                    raise
                except Exception as e:
                    logger.warning(f"Failed to process artifact {artifact['name']}: {e}")

        # 更新最后同步时间
        config.last_sync_at = datetime.now(UTC)
        await self.db.commit()

        logger.info(f"Sync completed for {config.workflow_name}: collected {collected} reports")
        return collected

    async def _check_existing_report(self, workflow_run_id: int) -> bool:
        """检查是否已存在该 workflow run 的报告"""
        stmt = select(ModelReport).where(
            ModelReport.workflow_run_id == workflow_run_id
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    def _match_artifacts(
        self,
        artifacts: list[dict[str, Any]],
        pattern: str | None
    ) -> list[dict[str, Any]]:
        """匹配 artifacts"""
        if not pattern:
            return artifacts

        return [
            artifact for artifact in artifacts
            if fnmatch.fnmatch(artifact["name"], pattern)
        ]

    async def _process_artifact(
        self,
        artifact_content: bytes,
        config: ModelSyncConfig,
        run: dict[str, Any],
        artifact_name: str = ""
    ) -> bool:
        """
        处理 artifact 内容

        Args:
            artifact_content: artifact 内容（ZIP 格式，即使只包含单个文件）
            config: 同步配置
            run: workflow run 信息
            artifact_name: artifact 名称（用于日志和推断）

        Returns:
            是否成功保存
        """
        # GitHub API 总是返回 ZIP 格式，所以直接处理 ZIP

        # 解析 file_patterns
        file_patterns = []
        if config.file_patterns:
            try:
                file_patterns = json.loads(config.file_patterns)
            except Exception as e:
                logger.warning(f"Invalid file_patterns JSON: {e}")
                file_patterns = []

        return await self._process_zip_artifact(
            artifact_content, config, run, file_patterns, artifact_name
        )

    async def _process_zip_artifact(
        self,
        artifact_content: bytes,
        config: ModelSyncConfig,
        run: dict[str, Any],
        file_patterns: list[str],
        artifact_name: str = ""
    ) -> bool:
        """
        处理 ZIP 格式的 artifact

        支持两种情况：
        1. 多文件 ZIP：包含多个文件，需要根据 file_patterns 查找报告文件
        2. 单文件 ZIP：只包含一个 JSON/YAML 文件，直接解析

        Args:
            artifact_content: ZIP 文件内容
            config: 同步配置
            run: workflow run 信息
            file_patterns: 文件匹配模式列表
            artifact_name: artifact 名称

        Returns:
            是否成功保存
        """
        import io
        import zipfile

        try:
            # 作为 zip 文件解压
            with zipfile.ZipFile(io.BytesIO(artifact_content)) as zip_file:
                # 获取 ZIP 内所有文件列表
                namelist = zip_file.namelist()

                # 过滤掉目录项
                file_list = [name for name in namelist if not name.endswith('/')]

                logger.info(f"Artifact '{artifact_name}' contains {len(file_list)} file(s): {file_list}")

                # 如果没有指定 file_patterns，使用默认模式
                if not file_patterns:
                    file_patterns = ["**/*.yaml", "**/*.yml", "**/*.json"]

                # 查找匹配的文件
                matched_files = []
                for name in file_list:
                    for pattern in file_patterns:
                        if fnmatch.fnmatch(name, pattern):
                            matched_files.append(name)
                            break

                if not matched_files:
                    # 如果没有匹配，但 ZIP 内只有一个文件，尝试直接解析
                    if len(file_list) == 1:
                        matched_files = [file_list[0]]
                        logger.info(f"No pattern match, but only 1 file in artifact, trying: {file_list[0]}")
                    else:
                        logger.warning(f"No matching files found in artifact for run {run['id']}")
                        return False

                # 读取第一个匹配的文件作为报告
                report_content = None
                report_type = "yaml"
                for file_path in matched_files:
                    try:
                        content = zip_file.read(file_path)
                        report_content = content.decode("utf-8")
                        # 根据扩展名判断类型
                        report_type = "json" if file_path.endswith(".json") else "yaml"
                        logger.info(f"Found report file: {file_path} ({report_type})")
                        break
                    except Exception as e:
                        logger.warning(f"Failed to read {file_path}: {e}")
                        continue

                if not report_content:
                    logger.warning("Could not read any report file from artifact")
                    return False

                # 解析报告
                if report_type == "yaml":
                    parsed_data = self.parser.parse_yaml_report(report_content)
                else:
                    parsed_data = self.parser.parse_json_report(report_content)

                # 获取模型配置（通过 model_name 匹配）
                model_name = parsed_data.get("model_name", "")
                if not model_name:
                    logger.warning("Model name not found in report")
                    return False

                stmt = select(ModelConfig).where(ModelConfig.model_name == model_name)
                result = await self.db.execute(stmt)
                model_config = result.scalar_one_or_none()

                if not model_config:
                    logger.warning(f"Model config not found for {model_name}")
                    return False

                # 评估 Pass/Fail（使用新模板的自动计算）
                pass_fail = parsed_data.get("pass_fail", "pass")
                auto_pass_fail = pass_fail

                # 创建报告
                report = ModelReport(
                    model_config_id=model_config.id,
                    workflow_run_id=run["id"],
                    report_json=parsed_data,
                    report_markdown=None,
                    pass_fail=pass_fail,
                    auto_pass_fail=auto_pass_fail,
                    manual_override=False,
                    metrics_json=parsed_data["metrics"],
                    vllm_version=parsed_data.get("vllm_version", ""),
                    hardware=parsed_data.get("hardware", ""),
                    # 新模板字段
                    dtype=parsed_data.get("dtype", ""),
                    features=parsed_data.get("features", []),
                    serve_cmd=parsed_data.get("serve_cmd", {}),
                    environment=parsed_data.get("environment", {}),
                    tasks=parsed_data.get("tasks", [])
                )

                self.db.add(report)
                await self.db.commit()
                await self.db.refresh(report)

                logger.info(f"Created report for model {model_name} from run {run['id']}")
                return True

        except zipfile.BadZipFile:
            logger.warning(f"Artifact is not a valid zip file for run {run['id']}")
            return False
        except Exception as e:
            logger.error(f"Failed to process artifact: {e}", exc_info=True)
            return False

    async def create_report_from_upload(
        self,
        model_config_id: int,
        report_content: str,
        content_type: str = "yaml",
        vllm_version: str | None = None,
        hardware: str | None = None
    ) -> ModelReport:
        """
        从手动上传的内容创建报告（支持新模板）

        Args:
            model_config_id: 模型配置 ID
            report_content: 报告内容（YAML 或 JSON）
            content_type: 内容类型 "yaml" 或 "json"
            vllm_version: vLLM 版本（如果上传参数未提供，则从报告内容中提取）
            hardware: 硬件类型（如果上传参数未提供，则从报告内容中提取）

        Returns:
            创建的报告对象
        """
        # 解析报告
        if content_type == "yaml":
            parsed_data = self.parser.parse_yaml_report(report_content)
        else:
            parsed_data = self.parser.parse_json_report(report_content)

        # 获取模型配置
        stmt = select(ModelConfig).where(ModelConfig.id == model_config_id)
        result = await self.db.execute(stmt)
        result.scalar_one()

        # 从报告内容中提取 vllm_version 和 hardware（如果上传参数未提供）
        if not vllm_version:
            vllm_version = parsed_data.get("vllm_version")
        if not hardware:
            hardware = parsed_data.get("hardware")

        # 使用新模板的 pass_fail（所有 task 都 pass 才算 pass）
        pass_fail = parsed_data.get("pass_fail", "pass")
        auto_pass_fail = pass_fail

        # 创建报告（支持新模板字段）
        report = ModelReport(
            model_config_id=model_config_id,
            report_json=parsed_data,
            report_markdown=None,
            pass_fail=pass_fail,
            auto_pass_fail=auto_pass_fail,
            manual_override=False,
            metrics_json=parsed_data["metrics"],
            vllm_version=vllm_version,
            hardware=hardware,
            # 新模板字段
            dtype=parsed_data.get("dtype", ""),
            features=parsed_data.get("features", []),
            serve_cmd=parsed_data.get("serve_cmd", {}),
            environment=parsed_data.get("environment", {}),
            tasks=parsed_data.get("tasks", [])
        )

        self.db.add(report)
        await self.db.commit()
        await self.db.refresh(report)

        return report
