"""
Collector 基础模块：租约领取、续约、优雅退出。

每个 Collector 实例通过 FOR UPDATE SKIP LOCKED 竞争领取任务，
使用 lease_token 做 fencing，支持 SIGTERM 优雅退出。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from dataclasses import dataclass

from sqlalchemy import bindparam, text

logger = logging.getLogger(__name__)


@dataclass
class TaskContext:
    """Collector 持有的任务上下文"""
    task_id: int
    lease_token: str
    lease_generation: int


class CollectorWorker:
    """
    采集 Worker 基类。

    用法：
        async def my_executor(ctx: TaskContext, renew_fn):
            ...  # 执行具体采集逻辑

        worker = CollectorWorker(
            node_id="collector-prod-1",
            capabilities=["python"],
            db_session_factory=SessionLocal,
            task_executor=my_executor,
        )
        await worker.run()
    """

    def __init__(
        self,
        node_id: str,
        capabilities: list[str],
        db_session_factory,
        task_executor=None,
        max_concurrent: int = 3,
        lease_ttl: int = 60,
        renew_interval: int = 20,
        poll_interval: int = 5,
        drain_timeout: int = 300,
    ):
        self.node_id = node_id
        self.capabilities = capabilities
        self._session_factory = db_session_factory
        self._task_executor = task_executor or self._execute_with_lease
        self._max_concurrent = max_concurrent
        self._lease_ttl = lease_ttl
        self._renew_interval = renew_interval
        self._poll_interval = poll_interval
        self._drain_timeout = drain_timeout

        self._draining = False
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._task_contexts: dict[int, TaskContext] = {}
        self._futures: dict[int, asyncio.Task] = {}
        self._heartbeat_task: asyncio.Task | None = None

    # ── 公共 API ──

    async def run_with_executor(self, executor):
        """使用自定义 executor 启动。"""
        self._task_executor = executor
        await self.run()

    async def run(self):
        """主循环：领取任务 → 执行 → 续约，直到收到 SIGTERM 后优雅退出。"""
        self._setup_signal_handlers()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("Collector %s started (capabilities=%s, max_concurrent=%d)",
                     self.node_id, self.capabilities, self._max_concurrent)

        while not self._draining:
            await self._semaphore.acquire()
            task_ctx = await self._claim_task()
            if task_ctx:
                future = asyncio.ensure_future(self._run_task_with_lease(task_ctx))
                self._futures[task_ctx.task_id] = future
                self._task_contexts[task_ctx.task_id] = task_ctx
                future.add_done_callback(
                    lambda f, tid=task_ctx.task_id: self._on_task_done(tid, f)
                )
            else:
                self._semaphore.release()
                await asyncio.sleep(self._poll_interval)

        # ── drain 阶段 ──
        remaining = len(self._futures)
        logger.info("Drain mode: %d tasks remaining", remaining)
        if remaining > 0:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._futures.values(), return_exceptions=True),
                    timeout=self._drain_timeout,
                )
            except TimeoutError:
                logger.warning("Drain timeout (%ds), cancelling remaining tasks", self._drain_timeout)
                futures = list(self._futures.values())
                for f in futures:
                    f.cancel()
                await asyncio.gather(*futures, return_exceptions=True)

        await self._flush_all_checkpoints()
        await self._release_all_leases()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            await asyncio.gather(self._heartbeat_task, return_exceptions=True)
        await self._write_heartbeat(running=False)
        logger.info("Collector %s shutdown complete", self.node_id)

    async def _run_task_with_lease(self, task_ctx: TaskContext) -> None:
        """Execute one task and persist its terminal state with lease fencing."""
        try:
            await self._task_executor(task_ctx, self._renew_lease)
        except asyncio.CancelledError:
            # Cancellation is shutdown/control flow, not a task failure.
            await self._release_task_lease(task_ctx)
            raise
        except Exception as exc:
            try:
                from infrastructure.clients.github_client import GitHubAuthenticationError

                await self._fail_task(
                    task_ctx.task_id,
                    task_ctx.lease_token,
                    str(exc)[:1000],
                    # A rejected credential cannot succeed on a retry.  Move
                    # it through the dead-letter path so the UI reports the
                    # real configuration failure instead of staying in
                    # "syncing" forever.
                    retry=not isinstance(exc, GitHubAuthenticationError),
                )
            except Exception:
                logger.exception("Failed to persist failure for task %d", task_ctx.task_id)
            raise
        else:
            completed = await self._complete_task(task_ctx.task_id, task_ctx.lease_token)
            if not completed:
                logger.warning(
                    "Task %d completed but its lease was no longer owned by %s",
                    task_ctx.task_id,
                    self.node_id,
                )

    async def _heartbeat_loop(self) -> None:
        while not self._draining:
            await self._write_heartbeat(running=True)
            await asyncio.sleep(20)

    async def _write_heartbeat(self, *, running: bool) -> None:
        """Publish process health and in-flight task count for API and operations."""
        try:
            async with self._session_factory() as db:
                await db.execute(
                    text(
                        """
                        INSERT INTO collector_heartbeats
                            (node_id, capabilities, running, active_tasks, pid, updated_at)
                        VALUES (:node_id, :capabilities, :running, :active_tasks, :pid, NOW())
                        ON DUPLICATE KEY UPDATE
                            capabilities = VALUES(capabilities),
                            running = VALUES(running),
                            active_tasks = VALUES(active_tasks),
                            pid = VALUES(pid),
                            updated_at = NOW()
                        """
                    ),
                    {
                        "node_id": self.node_id,
                        "capabilities": json.dumps(self.capabilities),
                        "running": running,
                        "active_tasks": len(self._futures),
                        "pid": os.getpid(),
                    },
                )
                await db.commit()
        except Exception as exc:
            logger.warning("Collector heartbeat write failed: %s", exc)

    async def _execute_with_lease(self, ctx: TaskContext, renew_fn=None):
        """
        子类重写此方法实现具体采集逻辑。

        默认每 renew_interval 秒续约一次，续约失败时停止执行。
        """
        raise NotImplementedError("subclass must implement _execute_with_lease")

    # ── 租约领取 ──

    async def _claim_task(self) -> TaskContext | None:
        """使用 FOR UPDATE SKIP LOCKED 领取一个 pending 或 expired 任务。"""
        lease_token = str(uuid.uuid4())
        async with self._session_factory() as db:
            async with db.begin():
                # 清理超限过期任务（防永久卡在 running）
                await db.execute(text("""
                    UPDATE collection_tasks
                    SET status = 'dead', lease_owner = NULL, lease_token = NULL,
                        lease_expiry = NULL, last_error = 'lease expired after max failures'
                    WHERE status = 'running' AND lease_expiry < NOW()
                      AND failure_count >= max_failures
                """))

                # Older workers could leave exhausted tasks as ``pending``.
                # They are intentionally excluded by the claim predicate, so
                # normalize them here instead of allowing an invisible queue
                # of permanently stuck tasks to accumulate.
                await db.execute(text("""
                    UPDATE collection_tasks
                    SET status = 'dead', lease_owner = NULL, lease_token = NULL,
                        lease_expiry = NULL, next_retry_at = NULL,
                        last_error = COALESCE(last_error, 'task exhausted max failures')
                    WHERE status = 'pending' AND failure_count >= max_failures
                """))

                # 领取任务
                result = await db.execute(
                    text("""
                        SELECT id FROM collection_tasks
                        WHERE (
                            status = 'pending'
                            OR (status = 'running' AND lease_expiry < NOW())
                        )
                        AND failure_count < max_failures
                        AND (required_capability IS NULL
                             OR required_capability IN :capabilities)
                        AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                        ORDER BY priority DESC, created_at
                        LIMIT 1
                        FOR UPDATE SKIP LOCKED
                    """).bindparams(bindparam("capabilities", expanding=True)),
                    {"capabilities": tuple(self.capabilities)},
                )
                row = result.fetchone()
                if not row:
                    return None

                task_id = row[0]
                await db.execute(
                    text("""
                        UPDATE collection_tasks
                        SET status = 'running',
                            lease_owner = :owner,
                            lease_token = :token,
                            lease_expiry = NOW() + INTERVAL :ttl SECOND,
                            lease_generation = lease_generation + 1,
                            execution_count = execution_count + 1,
                            failure_count = CASE
                                WHEN lease_owner IS NOT NULL AND lease_expiry < NOW()
                                THEN failure_count + 1
                                ELSE failure_count
                            END
                        WHERE id = :task_id
                    """),
                    {
                        "owner": self.node_id,
                        "token": lease_token,
                        "ttl": self._lease_ttl,
                        "task_id": task_id,
                    },
                )

                gen_row = await db.execute(
                    text("SELECT lease_generation FROM collection_tasks WHERE id = :id"),
                    {"id": task_id},
                )
                lease_generation = gen_row.scalar()

        return TaskContext(task_id=task_id, lease_token=lease_token, lease_generation=lease_generation)

    # ── 续约 ──

    async def _renew_lease(self, task_id: int, lease_token: str) -> bool:
        """续约，返回 True 表示成功。"""
        async with self._session_factory() as db:
            result = await db.execute(
                text("""
                    UPDATE collection_tasks
                    SET lease_expiry = NOW() + INTERVAL :ttl SECOND
                    WHERE id = :task_id
                      AND lease_owner = :owner
                      AND lease_token = :token
                      AND lease_expiry > NOW()
                """),
                {
                    "ttl": self._lease_ttl,
                    "task_id": task_id,
                    "owner": self.node_id,
                    "token": lease_token,
                },
            )
            await db.commit()
            return result.rowcount == 1

    # ── 检查点 ──

    async def _write_checkpoint(self, task_id: int, lease_token: str, checkpoint: dict):
        """写入检查点。"""
        async with self._session_factory() as db:
            await db.execute(
                text("""
                    UPDATE collection_tasks
                    SET checkpoint_data = :checkpoint
                    WHERE id = :task_id
                      AND lease_owner = :owner
                      AND lease_token = :token
                      AND lease_expiry > NOW()
                """),
                {
                    "checkpoint": json.dumps(checkpoint, ensure_ascii=False),
                    "task_id": task_id,
                    "owner": self.node_id,
                    "token": lease_token,
                },
            )
            await db.commit()

    # ── 完成任务 ──

    async def _complete_task(self, task_id: int, lease_token: str) -> bool:
        """标记任务完成。"""
        async with self._session_factory() as db:
            result = await db.execute(
                text("""
                    UPDATE collection_tasks
                    SET status = 'completed',
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expiry = NULL
                    WHERE id = :task_id
                      AND lease_owner = :owner
                      AND lease_token = :token
                      AND lease_expiry > NOW()
                """),
                {"task_id": task_id, "owner": self.node_id, "token": lease_token},
            )
            await db.commit()
            return result.rowcount == 1

    # ── 失败处理 ──

    async def _fail_task(self, task_id: int, lease_token: str, error: str, retry: bool):
        """标记任务失败。retry=True 时重置为 pending，否则标记为 dead。"""
        async with self._session_factory() as db:
            await db.execute(
                text("""
                    UPDATE collection_tasks
                    SET status = CASE
                            WHEN :retry AND failure_count < max_failures THEN 'pending'
                            ELSE 'dead'
                        END,
                        failure_count = failure_count + 1,
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expiry = NULL,
                        next_retry_at = CASE
                            WHEN :retry AND failure_count < max_failures
                            THEN NOW() + INTERVAL 1 MINUTE
                            ELSE NULL
                        END,
                        last_error = :error
                    WHERE id = :task_id
                      AND lease_owner = :owner
                      AND lease_token = :token
                """),
                {
                    "retry": retry,
                    "error": error,
                    "task_id": task_id,
                    "owner": self.node_id,
                    "token": lease_token,
                },
            )
            await db.commit()

    # ── 生命周期 ──

    async def _release_task_lease(self, task_ctx: TaskContext) -> None:
        """Return a cancelled task to pending without counting a failure."""
        async with self._session_factory() as db:
            await db.execute(
                text("""
                    UPDATE collection_tasks
                    SET status = 'pending',
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expiry = NULL,
                        next_retry_at = NOW()
                    WHERE id = :task_id
                      AND lease_owner = :owner
                      AND lease_token = :token
                """),
                {
                    "task_id": task_ctx.task_id,
                    "owner": self.node_id,
                    "token": task_ctx.lease_token,
                },
            )
            await db.commit()

    def _on_task_done(self, task_id: int, future: asyncio.Task):
        """协程完成/异常/取消时清理。"""
        self._futures.pop(task_id, None)
        self._task_contexts.pop(task_id, None)
        self._semaphore.release()
        if future.cancelled():
            logger.warning("Task %d was cancelled", task_id)
        else:
            exc = future.exception()
            if exc:
                logger.error("Task %d failed: %s", task_id, exc)

    async def _flush_all_checkpoints(self):
        """drain 后刷新所有检查点。"""
        for task_id, ctx in list(self._task_contexts.items()):
            try:
                async with self._session_factory() as db:
                    await db.execute(
                        text("""
                            UPDATE collection_tasks
                            SET checkpoint_data = COALESCE(checkpoint_data, JSON_OBJECT())
                            WHERE id = :task_id
                              AND lease_owner = :owner
                              AND lease_token = :token
                        """),
                        {"task_id": task_id, "owner": self.node_id, "token": ctx.lease_token},
                    )
                    await db.commit()
            except Exception as exc:
                logger.error("Failed to flush checkpoint for task %d: %s", task_id, exc)

    async def _release_all_leases(self):
        """释放所有租约（计划内操作，不加 failure_count）。"""
        for task_id, ctx in list(self._task_contexts.items()):
            try:
                async with self._session_factory() as db:
                    await db.execute(
                        text("""
                            UPDATE collection_tasks
                            SET status = 'pending',
                                lease_owner = NULL, lease_token = NULL,
                                lease_expiry = NULL, next_retry_at = NOW()
                            WHERE id = :task_id
                              AND lease_owner = :owner
                              AND lease_token = :token
                        """),
                        {"task_id": task_id, "owner": self.node_id, "token": ctx.lease_token},
                    )
                    await db.commit()
            except Exception as exc:
                logger.error("Failed to release lease for task %d: %s", task_id, exc)
        self._task_contexts.clear()

    def _setup_signal_handlers(self):
        """注册 SIGTERM/SIGINT 处理器。"""
        def _handler(signum, frame):
            logger.info("Received %s, entering drain mode", signal.Signals(signum).name)
            self._draining = True

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handler, sig, None)
            except NotImplementedError:
                # Windows 不支持 add_signal_handler
                signal.signal(sig, _handler)
