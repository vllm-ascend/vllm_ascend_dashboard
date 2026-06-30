"""回归测试：DB 日志 handler 不阻塞事件循环 + app_logs 表创建 + 反馈循环断开。

复现 PR #92 的启动卡死 bug：_db_log_worker 为 async 函数却直接调用阻塞的
queue.Queue.get(timeout=1)，在 uvicorn 事件循环线程中执行会阻塞事件循环，
导致 lifespan 卡在 create_all。修复后 get 通过 run_in_executor 移到线程池。
"""
import asyncio
import time

from app.core import logging as dblog
from app.models import AppLog, Base


def test_applog_model_registered():
    """AppLog 模型应注册到 Base.metadata，使 create_all 创建 app_logs 表。"""
    table_names = [t.name for t in Base.metadata.sorted_tables]
    assert "app_logs" in table_names, "app_logs 表未注册到 metadata，create_all 不会建表"


def test_applog_columns():
    """AppLog 列应与 _flush_batch 的 INSERT 列对应。"""
    cols = {c.name for c in AppLog.__table__.columns}
    expected = {"id", "timestamp", "level", "module", "function_name", "line_number", "message", "traceback"}
    assert expected.issubset(cols), f"缺少列: {expected - cols}"


def test_worker_logger_no_propagate():
    """worker logger 不传播到 root，避免 flush 失败的 warning 回流队列形成反馈循环。"""
    assert dblog._worker_logger.propagate is False


def test_worker_does_not_block_event_loop():
    """worker 的阻塞 queue.get 必须通过 run_in_executor 执行，不阻塞事件循环。

    旧 bug：直接在 async worker 中 _log_queue.get(timeout=1) 会阻塞事件循环 1s，
    并发任务无法推进。修复后并发 sleep(0.3) 应在 <0.8s 完成。
    """
    async def fake_flush(entries):
        return None

    async def main():
        dblog._flush_batch = fake_flush  # 避免 DB 依赖
        worker = asyncio.create_task(dblog._db_log_worker())

        start = time.monotonic()
        await asyncio.sleep(0.3)
        elapsed = time.monotonic() - start

        # 喂入哨兵让 worker 的 get 立即返回，便于取消
        dblog._log_queue.put_nowait({"sentinel": True})
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        return elapsed

    elapsed = asyncio.run(main())
    assert elapsed < 0.8, f"事件循环被 worker 阻塞：elapsed={elapsed:.2f}s（应 <0.8s）"
