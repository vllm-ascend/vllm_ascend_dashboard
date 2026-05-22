"""
每日数据文件存储服务
将每日 PR/Issue/Commit 数据和AI 总结存储为外部文件
"""
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class DailyDataFileStore:
    """每日数据文件存储"""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        初始化文件存储

        Args:
            base_dir: 基础目录，默认为 settings.DATA_DIR/daily-data
        """
        if base_dir is None:
            base_dir = Path(settings.DATA_DIR) / "daily-data"
        self.base_dir = base_dir
        # 确保目录存在
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_project_dir(self, project: str) -> Path:
        """获取项目目录"""
        project_dir = self.base_dir / project
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir

    def _get_summary_dir(self, project: str) -> Path:
        """获取总结目录"""
        summary_dir = self._get_project_dir(project) / "summaries"
        summary_dir.mkdir(parents=True, exist_ok=True)
        return summary_dir

    def _get_data_file_path(self, project: str, data_date: date) -> Path:
        """获取每日数据文件路径"""
        return self._get_project_dir(project) / f"{data_date.isoformat()}.json"

    def _get_summary_file_path(self, project: str, data_date: date) -> Path:
        """获取总结 Markdown 文件路径"""
        return self._get_summary_dir(project) / f"{data_date.isoformat()}.md"

    def _get_summary_meta_file_path(self, project: str, data_date: date) -> Path:
        """获取总结元数据文件路径"""
        return self._get_summary_dir(project) / f"{data_date.isoformat()}.meta.json"

    # ============ 每日数据读写 ============

    async def save_daily_data(
        self,
        project: str,
        data_date: date,
        prs: list[dict],
        issues: list[dict],
        commits: list[dict],
        fetched_at: Optional[datetime] = None
    ) -> Path:
        """
        保存每日数据到 JSON 文件

        Args:
            project: 项目标识
            data_date: 数据日期
            prs: PR 列表
            issues: Issue 列表
            commits: Commit 列表
            fetched_at: 抓取时间

        Returns:
            文件路径
        """
        file_path = self._get_data_file_path(project, data_date)

        data = {
            "project": project,
            "data_date": data_date.isoformat(),
            "fetched_at": fetched_at.isoformat() if fetched_at else datetime.now().isoformat(),
            "pull_requests": prs,
            "issues": issues,
            "commits": commits,
            "counts": {
                "prs": len(prs),
                "issues": len(issues),
                "commits": len(commits),
            }
        }

        # 原子写入：先写临时文件再重命名
        temp_path = file_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            temp_path.rename(file_path)
            logger.info(f"Saved daily data for {project} on {data_date} to {file_path}")
            return file_path
        except Exception as e:
            # 清理临时文件
            if temp_path.exists():
                temp_path.unlink()
            logger.error(f"Failed to save daily data: {e}")
            raise

    async def load_daily_data(self, project: str, data_date: date) -> Optional[dict]:
        """
        从 JSON 文件加载每日数据

        Args:
            project: 项目标识
            data_date: 数据日期

        Returns:
            数据字典或 None（文件不存在）
        """
        file_path = self._get_data_file_path(project, data_date)

        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception as e:
            logger.error(f"Failed to load daily data from {file_path}: {e}")
            return None

    async def delete_daily_data(self, project: str, data_date: date) -> bool:
        """
        删除每日数据文件

        Args:
            project: 项目标识
            data_date: 数据日期

        Returns:
            是否删除成功
        """
        file_path = self._get_data_file_path(project, data_date)

        if file_path.exists():
            try:
                file_path.unlink()
                logger.info(f"Deleted daily data for {project} on {data_date}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete daily data: {e}")
                return False
        return False

    async def list_available_dates(self, project: str, limit: int = 30) -> list[str]:
        """
        列出有数据的日期

        Args:
            project: 项目标识
            limit: 最大返回数量

        Returns:
            日期字符串列表（降序）
        """
        project_dir = self.base_dir / project
        dates = []

        # 如果项目目录不存在，返回空列表（不创建目录）
        if not project_dir.exists():
            return dates

        for file_path in project_dir.glob("*.json"):
            # 跳过 summaries 目录
            if "summaries" in str(file_path):
                continue
            date_str = file_path.stem  # YYYY-MM-DD
            dates.append(date_str)

        # 降序排序并限制数量
        dates.sort(reverse=True)
        return dates[:limit]

    # ============ AI 总结读写 ============

    async def save_summary(
        self,
        project: str,
        data_date: date,
        summary_markdown: str,
        metadata: dict
    ) -> Path:
        """
        保存 AI 总结到 Markdown 文件 + 元数据 JSON

        Args:
            project: 项目标识
            data_date: 数据日期
            summary_markdown: Markdown 内容
            metadata: 元数据（pr_count, issue_count, commit_count, llm_provider 等）

        Returns:
            Markdown 文件路径
        """
        md_path = self._get_summary_file_path(project, data_date)
        meta_path = self._get_summary_meta_file_path(project, data_date)

        # 保存 Markdown
        temp_md = md_path.with_suffix(".tmp")
        try:
            with open(temp_md, "w", encoding="utf-8") as f:
                f.write(summary_markdown)
            temp_md.rename(md_path)
        except Exception as e:
            if temp_md.exists():
                temp_md.unlink()
            logger.error(f"Failed to save summary markdown: {e}")
            raise

        # 保存元数据
        temp_meta = meta_path.with_suffix(".tmp")
        try:
            meta_data = {
                "project": project,
                "data_date": data_date.isoformat(),
                **metadata
            }
            with open(temp_meta, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
            temp_meta.rename(meta_path)
            logger.info(f"Saved summary for {project} on {data_date}")
            return md_path
        except Exception as e:
            if temp_meta.exists():
                temp_meta.unlink()
            # 清理 Markdown 文件
            if md_path.exists():
                md_path.unlink()
            logger.error(f"Failed to save summary metadata: {e}")
            raise

    async def load_summary(self, project: str, data_date: date) -> Optional[dict]:
        """
        加载 AI 总结

        Args:
            project: 项目标识
            data_date: 数据日期

        Returns:
            包含 markdown 和 metadata 的字典或 None
        """
        md_path = self._get_summary_file_path(project, data_date)
        meta_path = self._get_summary_meta_file_path(project, data_date)

        if not md_path.exists():
            return None

        try:
            # 读取 Markdown
            with open(md_path, "r", encoding="utf-8") as f:
                markdown = f.read()

            # 读取元数据
            metadata = {}
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)

            return {
                "project": project,
                "data_date": data_date.isoformat(),
                "summary_markdown": markdown,
                **metadata
            }
        except Exception as e:
            logger.error(f"Failed to load summary from {md_path}: {e}")
            return None

    async def delete_summary(self, project: str, data_date: date) -> bool:
        """
        删除 AI 总结文件

        Args:
            project: 项目标识
            data_date: 数据日期

        Returns:
            是否删除成功
        """
        md_path = self._get_summary_file_path(project, data_date)
        meta_path = self._get_summary_meta_file_path(project, data_date)

        deleted = False
        for path in [md_path, meta_path]:
            if path.exists():
                try:
                    path.unlink()
                    deleted = True
                except Exception as e:
                    logger.error(f"Failed to delete {path}: {e}")

        return deleted
