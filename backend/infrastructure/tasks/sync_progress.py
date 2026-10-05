"""
同步进度跟踪器
用于跟踪和报告数据同步任务的进度
"""
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


class SyncProgress:
    """同步进度跟踪器"""

    def __init__(self, total_workflows: int = 0):
        """
        初始化进度跟踪器

        Args:
            total_workflows: 总 workflow 数量
        """
        self.total_workflows = total_workflows
        self.completed_workflows = 0
        self.current_workflow: str | None = None
        self.total_collected = 0
        self.status = "idle"  # idle, running, completed, failed
        self.error_message: str | None = None
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.workflow_details: dict[str, Any] = {}

    def start(self):
        """开始同步"""
        self.status = "running"
        self.started_at = datetime.now(UTC)
        self.error_message = None
        logger.info(f"Sync started: {self.total_workflows} workflows")

    def update_workflow_progress(
        self,
        workflow_name: str,
        collected: int,
        status: str = "completed",
        error: str | None = None,
    ):
        """
        更新单个 workflow 的进度

        Args:
            workflow_name: workflow 名称
            collected: 采集的记录数
            status: 状态 (running, completed, failed)
        """
        self.current_workflow = workflow_name
        self.workflow_details[workflow_name] = {
            "collected": collected,
            "status": status,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if error:
            self.workflow_details[workflow_name]["error"] = error
        if status == "completed":
            self.completed_workflows += 1
        logger.info(f"Workflow {workflow_name}: {collected} runs collected, status: {status}")

    def update_collected_count(self, count: int):
        """
        更新已采集记录数（实时累加）

        Args:
            count: 新增的记录数
        """
        self.total_collected += count
        logger.debug(f"Total collected updated: {self.total_collected}")

    def complete(self):
        """同步完成"""
        self.status = "completed"
        self.completed_at = datetime.now(UTC)
        logger.info(f"Sync completed: {self.total_collected} total runs")

    def fail(self, error_message: str):
        """同步失败"""
        self.status = "failed"
        self.error_message = error_message
        self.completed_at = datetime.now(UTC)
        logger.error(f"Sync failed: {error_message}")

    def get_progress(self) -> dict[str, Any]:
        """
        获取当前进度

        Returns:
            进度信息字典
        """
        progress_percentage = 0
        if self.total_workflows > 0:
            progress_percentage = round(
                (self.completed_workflows / self.total_workflows) * 100, 2
            )

        elapsed_seconds = None
        if self.started_at:
            end_time = self.completed_at or datetime.now(UTC)
            elapsed_seconds = (end_time - self.started_at).total_seconds()

        return {
            "status": self.status,
            "progress_percentage": progress_percentage,
            "total_workflows": self.total_workflows,
            "completed_workflows": self.completed_workflows,
            "current_workflow": self.current_workflow,
            "total_collected": self.total_collected,
            "workflow_details": self.workflow_details,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "elapsed_seconds": elapsed_seconds,
        }


# 全局进度跟踪器实例
_sync_progress: SyncProgress | None = None


def get_sync_progress() -> SyncProgress:
    """获取全局进度跟踪器实例"""
    global _sync_progress
    if _sync_progress is None:
        _sync_progress = SyncProgress()
    return _sync_progress


def reset_sync_progress():
    """重置进度跟踪器"""
    global _sync_progress
    _sync_progress = SyncProgress()
    logger.debug("Sync progress tracker reset")
