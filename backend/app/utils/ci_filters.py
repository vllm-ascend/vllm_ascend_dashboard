"""CI 统计时间窗口过滤工具。

配置的小时为北京时间（UTC+8），存储的 started_at 为 UTC。
通过将配置小时转换为 UTC 小时后比较，避免数据库时区函数依赖。
"""
from sqlalchemy import Integer, and_, cast, func, or_

from app.db.base import _is_sqlite


def _hour_expr(col):
    """提取 UTC 小时，兼容 MySQL 和 SQLite。"""
    if _is_sqlite:
        return cast(func.strftime('%H', col), Integer)
    return func.hour(col)


def build_workflow_time_filter(model_cls, wf_configs: list):
    """构建按 workflow 的时间窗口过滤条件。

    Args:
        model_cls: 模型类（CIResult 或 CIJob），需有 workflow_name 和 started_at 属性
        wf_configs: [(workflow_name, stats_start_hour, stats_end_hour), ...]
                    小时为北京时间（UTC+8），None 表示不过滤

    Returns:
        SQLAlchemy OR 条件，或 None（无 workflow）
    """
    conditions = []
    for wf_name, start_h, end_h in wf_configs:
        wf_cond = model_cls.workflow_name == wf_name
        if start_h is not None and end_h is not None:
            start_utc = (start_h - 8) % 24
            end_utc = (end_h - 8) % 24
            hour = _hour_expr(model_cls.started_at)
            if start_utc >= end_utc:
                wf_cond = and_(wf_cond, or_(hour >= start_utc, hour < end_utc))
            else:
                wf_cond = and_(wf_cond, hour >= start_utc, hour < end_utc)
        conditions.append(wf_cond)
    return or_(*conditions) if conditions else None
