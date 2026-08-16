"""
TaskManager: collection_tasks 表操作。

Scheduler 创建任务记录，Collector 通过 FOR UPDATE SKIP LOCKED 竞争领取。
支持 Scheduler 直接执行（兼容现有模式）和 Collector 领取执行双模运行。
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class TaskManager:
    """collection_tasks 表操作，不持有数据库会话。"""

    @staticmethod
    async def create_task(
        db: AsyncSession,
        task_type: str,
        task_params: dict,
        dedupe_key: str,
        required_capability: str | None = None,
        priority: int = 0,
    ) -> int | None:
        """
        Scheduler 创建任务记录。
        返回 task_id；如果 dedupe_key 对应的活跃任务已存在则跳过。
        """
        import json as _json
        result = await db.execute(
            text("""
                INSERT IGNORE INTO collection_tasks
                    (task_type, task_params, dedupe_key, required_capability, priority)
                VALUES (:task_type, :task_params, :dedupe_key, :capability, :priority)
            """),
            {
                "task_type": task_type,
                "task_params": _json.dumps(task_params),
                "dedupe_key": dedupe_key,
                "capability": required_capability,
                "priority": priority,
            },
        )
        if result.rowcount == 0:
            logger.debug("Task already exists for dedupe_key=%s", dedupe_key)
            return None

        task_id = result.lastrowid
        logger.info("Created task %d type=%s dedupe_key=%s", task_id, task_type, dedupe_key)
        return task_id

    @staticmethod
    async def start_task(db: AsyncSession, task_id: int, owner: str) -> bool:
        """Scheduler 直接执行时，标记任务开始（不经过租约竞争）。"""
        result = await db.execute(
            text("""
                UPDATE collection_tasks
                SET status = 'running',
                    lease_owner = :owner,
                    lease_token = :token,
                    lease_expiry = NOW() + INTERVAL 3600 SECOND,
                    lease_generation = lease_generation + 1,
                    execution_count = execution_count + 1
                WHERE id = :task_id AND status = 'pending'
            """),
            {"owner": owner, "token": str(uuid.uuid4()), "task_id": task_id},
        )
        return result.rowcount == 1

    @staticmethod
    async def update_checkpoint(
        db: AsyncSession, task_id: int, checkpoint: dict
    ):
        """更新检查点。"""
        import json as _json

        await db.execute(
            text("""
                UPDATE collection_tasks
                SET checkpoint_data = :checkpoint
                WHERE id = :task_id
            """),
            {"checkpoint": _json.dumps(checkpoint), "task_id": task_id},
        )

    @staticmethod
    async def complete_task(db: AsyncSession, task_id: int):
        """标记任务完成。"""
        await db.execute(
            text("""
                UPDATE collection_tasks
                SET status = 'completed',
                    lease_owner = NULL, lease_token = NULL, lease_expiry = NULL
                WHERE id = :task_id
            """),
            {"task_id": task_id},
        )

    @staticmethod
    async def fail_task(db: AsyncSession, task_id: int, error: str):
        """标记任务失败（可重试）。"""
        await db.execute(
            text("""
                UPDATE collection_tasks
                SET status = CASE WHEN failure_count + 1 >= max_failures THEN 'dead' ELSE 'pending' END,
                    failure_count = failure_count + 1,
                    lease_owner = NULL, lease_token = NULL, lease_expiry = NULL,
                    next_retry_at = CASE WHEN failure_count + 1 >= max_failures THEN NULL ELSE NOW() + INTERVAL 1 MINUTE END,
                    last_error = :error
                WHERE id = :task_id
            """),
            {"error": error, "task_id": task_id},
        )
