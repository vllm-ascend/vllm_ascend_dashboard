"""
数据库迁移脚本：将每日数据从数据库迁移到文件存储

使用方法：
    python -m backend.scripts.migrate_daily_data_to_files

功能：
    1. 从数据库读取所有每日数据（PR/Issue/Commit）
    2. 导出到文件存储（data/daily-data/{project}/{date}.json）
    3. 从数据库读取所有 AI 总结
    4. 导出到文件存储（data/daily-data/{project}/summaries/{date}.md + .meta.json）
    5. 验证迁移结果
    6. 可选：清理数据库中的旧数据
"""
import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import SessionLocal
from app.models.daily_summary import DailyPR, DailyIssue, DailyCommit, DailySummary
from app.services.daily_data_file_store import DailyDataFileStore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DailyDataMigrator:
    """每日数据迁移器"""

    def __init__(self):
        self.file_store = DailyDataFileStore()
        self.stats = {
            "projects": set(),
            "daily_data_migrated": 0,
            "summaries_migrated": 0,
            "errors": [],
        }

    async def migrate_all(self, cleanup_db: bool = False):
        """
        执行完整迁移

        Args:
            cleanup_db: 是否在迁移后清理数据库中的旧数据
        """
        logger.info("=" * 60)
        logger.info("开始迁移每日数据到文件存储")
        logger.info("=" * 60)

        async with SessionLocal() as session:
            # 1. 迁移每日数据（PR/Issue/Commit）
            logger.info("\n[1/3] 迁移每日数据...")
            await self._migrate_daily_data(session)

            # 2. 迁移 AI 总结
            logger.info("\n[2/3] 迁移 AI 总结...")
            await self._migrate_summaries(session)

            # 3. 验证迁移结果
            logger.info("\n[3/3] 验证迁移结果...")
            await self._verify_migration(session)

        # 打印统计信息
        self._print_stats()

        # 可选：清理数据库
        if cleanup_db:
            logger.info("\n清理数据库中的旧数据...")
            async with SessionLocal() as session:
                await self._cleanup_database(session)
                await session.commit()

        logger.info("\n迁移完成！")

    async def _migrate_daily_data(self, session: AsyncSession):
        """迁移每日数据（PR/Issue/Commit）"""
        # 获取所有不同的项目和日期组合
        projects_dates = await self._get_unique_project_dates(session)

        total = len(projects_dates)
        logger.info(f"找到 {total} 个项目-日期组合需要迁移")

        for idx, (project, data_date) in enumerate(projects_dates, 1):
            try:
                # 检查文件是否已存在
                existing = await self.file_store.load_daily_data(project, data_date)
                if existing:
                    logger.info(f"[{idx}/{total}] 跳过 {project} {data_date}（文件已存在）")
                    continue

                # 从数据库读取数据
                prs = await self._load_prs(session, project, data_date)
                issues = await self._load_issues(session, project, data_date)
                commits = await self._load_commits(session, project, data_date)

                # 获取 fetched_at（取最早的一条）
                fetched_at = None
                if prs:
                    fetched_at = min(pr.fetched_at for pr in prs if pr.fetched_at)
                elif issues:
                    fetched_at = min(issue.fetched_at for issue in issues if issue.fetched_at)
                elif commits:
                    fetched_at = min(commit.fetched_at for commit in commits if commit.fetched_at)

                # 转换为字典
                pr_dicts = [self._model_to_dict(pr) for pr in prs]
                issue_dicts = [self._model_to_dict(issue) for issue in issues]
                commit_dicts = [self._model_to_dict(commit) for commit in commits]

                # 保存到文件
                await self.file_store.save_daily_data(
                    project=project,
                    data_date=data_date,
                    prs=pr_dicts,
                    issues=issue_dicts,
                    commits=commit_dicts,
                    fetched_at=fetched_at,
                )

                self.stats["daily_data_migrated"] += 1
                self.stats["projects"].add(project)
                logger.info(
                    f"[{idx}/{total}] 已迁移 {project} {data_date}: "
                    f"{len(prs)} PRs, {len(issues)} Issues, {len(commits)} Commits"
                )

            except Exception as e:
                error_msg = f"迁移 {project} {data_date} 失败: {e}"
                logger.error(error_msg)
                self.stats["errors"].append(error_msg)

    async def _migrate_summaries(self, session: AsyncSession):
        """迁移 AI 总结"""
        # 获取所有总结
        stmt = select(DailySummary).order_by(DailySummary.project, DailySummary.data_date)
        result = await session.execute(stmt)
        summaries = result.scalars().all()

        total = len(summaries)
        logger.info(f"找到 {total} 个 AI 总结需要迁移")

        for idx, summary in enumerate(summaries, 1):
            try:
                # 检查文件是否已存在
                existing = await self.file_store.load_summary(summary.project, summary.data_date)
                if existing:
                    logger.info(f"[{idx}/{total}] 跳过 {summary.project} {summary.data_date}（文件已存在）")
                    continue

                # 准备元数据
                metadata = {
                    "has_data": summary.has_data,
                    "pr_count": summary.pr_count,
                    "issue_count": summary.issue_count,
                    "commit_count": summary.commit_count,
                    "llm_provider": summary.llm_provider,
                    "llm_model": summary.llm_model,
                    "prompt_tokens": summary.prompt_tokens,
                    "completion_tokens": summary.completion_tokens,
                    "generation_time_seconds": summary.generation_time_seconds,
                    "status": summary.status,
                    "error_message": summary.error_message,
                    "generated_at": summary.generated_at.isoformat() if summary.generated_at else None,
                    "regenerated_at": summary.regenerated_at.isoformat() if summary.regenerated_at else None,
                }

                # 保存到文件
                await self.file_store.save_summary(
                    project=summary.project,
                    data_date=summary.data_date,
                    summary_markdown=summary.summary_markdown,
                    metadata=metadata,
                )

                self.stats["summaries_migrated"] += 1
                self.stats["projects"].add(summary.project)
                logger.info(
                    f"[{idx}/{total}] 已迁移总结 {summary.project} {summary.data_date} "
                    f"(status={summary.status})"
                )

            except Exception as e:
                error_msg = f"迁移总结 {summary.project} {summary.data_date} 失败: {e}"
                logger.error(error_msg)
                self.stats["errors"].append(error_msg)

    async def _verify_migration(self, session: AsyncSession):
        """验证迁移结果"""
        # 统计数据库中的数据量
        db_prs = await session.execute(select(func.count(DailyPR.id)))
        db_prs_count = db_prs.scalar() or 0

        db_issues = await session.execute(select(func.count(DailyIssue.id)))
        db_issues_count = db_issues.scalar() or 0

        db_commits = await session.execute(select(func.count(DailyCommit.id)))
        db_commits_count = db_commits.scalar() or 0

        db_summaries = await session.execute(select(func.count(DailySummary.id)))
        db_summaries_count = db_summaries.scalar() or 0

        logger.info(f"\n数据库记录数:")
        logger.info(f"  - PRs: {db_prs_count}")
        logger.info(f"  - Issues: {db_issues_count}")
        logger.info(f"  - Commits: {db_commits_count}")
        logger.info(f"  - Summaries: {db_summaries_count}")

        # 统计文件存储中的数据量
        file_data_count = self.stats["daily_data_migrated"]
        file_summary_count = self.stats["summaries_migrated"]

        logger.info(f"\n文件存储新增数:")
        logger.info(f"  - 每日数据文件: {file_data_count}")
        logger.info(f"  - AI 总结文件: {file_summary_count}")

        if self.stats["errors"]:
            logger.warning(f"\n迁移错误数: {len(self.stats['errors'])}")
            for error in self.stats["errors"][:5]:  # 只显示前 5 个错误
                logger.warning(f"  - {error}")

    def _print_stats(self):
        """打印统计信息"""
        logger.info("\n" + "=" * 60)
        logger.info("迁移统计")
        logger.info("=" * 60)
        logger.info(f"涉及项目: {', '.join(sorted(self.stats['projects']))}")
        logger.info(f"迁移每日数据文件: {self.stats['daily_data_migrated']}")
        logger.info(f"迁移 AI 总结文件: {self.stats['summaries_migrated']}")
        logger.info(f"错误数: {len(self.stats['errors'])}")
        logger.info("=" * 60)

    async def _cleanup_database(self, session: AsyncSession):
        """清理数据库中的旧数据"""
        try:
            # 删除所有每日数据
            await session.execute(DailyPR.__table__.delete())
            await session.execute(DailyIssue.__table__.delete())
            await session.execute(DailyCommit.__table__.delete())
            await session.execute(DailySummary.__table__.delete())

            await session.commit()
            logger.info("已清理数据库中的旧数据")

        except Exception as e:
            logger.error(f"清理数据库失败: {e}")
            await session.rollback()
            raise

    async def _get_unique_project_dates(self, session: AsyncSession) -> list[tuple[str, date]]:
        """获取所有不同的项目和日期组合"""
        # 从 PRs 获取
        pr_stmt = select(DailyPR.project, DailyPR.data_date).where(
            DailyPR.data_date.isnot(None)
        ).distinct()
        pr_result = await session.execute(pr_stmt)
        project_dates = set(pr_result.all())

        # 从 Issues 获取
        issue_stmt = select(DailyIssue.project, DailyIssue.data_date).where(
            DailyIssue.data_date.isnot(None)
        ).distinct()
        issue_result = await session.execute(issue_stmt)
        project_dates.update(issue_result.all())

        # 从 Commits 获取
        commit_stmt = select(DailyCommit.project, DailyCommit.data_date).where(
            DailyCommit.data_date.isnot(None)
        ).distinct()
        commit_result = await session.execute(commit_stmt)
        project_dates.update(commit_result.all())

        # 从 Summaries 获取
        summary_stmt = select(DailySummary.project, DailySummary.data_date).where(
            DailySummary.data_date.isnot(None)
        ).distinct()
        summary_result = await session.execute(summary_stmt)
        project_dates.update(summary_result.all())

        return sorted(project_dates)

    async def _load_prs(self, session: AsyncSession, project: str, data_date: date):
        """加载指定项目和日期的 PRs"""
        stmt = select(DailyPR).where(
            DailyPR.project == project,
            DailyPR.data_date == data_date
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def _load_issues(self, session: AsyncSession, project: str, data_date: date):
        """加载指定项目和日期的 Issues"""
        stmt = select(DailyIssue).where(
            DailyIssue.project == project,
            DailyIssue.data_date == data_date
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    async def _load_commits(self, session: AsyncSession, project: str, data_date: date):
        """加载指定项目和日期的 Commits"""
        stmt = select(DailyCommit).where(
            DailyCommit.project == project,
            DailyCommit.data_date == data_date
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    def _model_to_dict(self, obj) -> dict:
        """SQLAlchemy 模型转字典"""
        return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="迁移每日数据到文件存储")
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="迁移后清理数据库中的旧数据"
    )
    args = parser.parse_args()

    migrator = DailyDataMigrator()
    await migrator.migrate_all(cleanup_db=args.cleanup)


if __name__ == "__main__":
    asyncio.run(main())
