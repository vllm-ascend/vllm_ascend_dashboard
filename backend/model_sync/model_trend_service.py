"""
模型趋势数据服务
生成模型指标随时间变化的趋势数据
"""
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from infrastructure.persistence.models import ModelReport

logger = logging.getLogger(__name__)


class ModelTrendService:
    """模型趋势数据服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_trend_data(
        self,
        model_config_id: int,
        days: int = 30,
        metric_keys: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """
        获取模型趋势数据

        Args:
            model_config_id: 模型配置 ID
            days: 获取多少天的数据
            metric_keys: 需要提取的 metric keys，None 表示提取所有

        Returns:
            趋势数据列表：
            [
                {
                    "date": "2026-03-20",
                    "report_id": 123,
                    "pass_fail": "pass",
                    "metrics": {
                        "gsm8k.exact_match": 0.89,
                        "ceval-valid.acc": 0.84
                    }
                },
                ...
            ]
        """
        # 查询指定时间范围内的报告
        cutoff_date = datetime.now(UTC) - timedelta(days=days)

        stmt = (
            select(ModelReport)
            .where(ModelReport.model_config_id == model_config_id)
            .where(ModelReport.created_at >= cutoff_date)
            .order_by(ModelReport.created_at.asc())
        )

        result = await self.db.execute(stmt)
        reports = result.scalars().all()

        trend_data = []
        for report in reports:
            # 解析 metrics（JSON 字段自动解析为 dict）
            metrics = {}
            if report.metrics_json:
                try:
                    all_metrics = report.metrics_json
                    # 兼容旧数据：如果是字符串，手动解析
                    if isinstance(all_metrics, str):
                        import json
                        all_metrics = json.loads(all_metrics)
                    if metric_keys:
                        # 只提取指定的 metrics
                        for key in metric_keys:
                            if key in all_metrics:
                                metrics[key] = all_metrics[key]
                    else:
                        # 提取所有 metrics
                        metrics = all_metrics
                except Exception as e:
                    logger.warning(f"Failed to parse metrics_json for report {report.id}: {e}")

            trend_data.append({
                "date": report.created_at.strftime("%Y-%m-%d"),
                "datetime": report.created_at.isoformat(),
                "report_id": report.id,
                "pass_fail": report.pass_fail,
                "metrics": metrics,
                "vllm_version": report.vllm_version,
                "hardware": report.hardware,
                # 添加 tasks 数据（从 report_json 中获取）
                "tasks": report.report_json.get('tasks', []) if report.report_json and isinstance(report.report_json, dict) else []
            })

        return trend_data

    async def get_key_metrics_trend(
        self,
        model_config_id: int,
        key_metrics: list[str],
        days: int = 30
    ) -> dict[str, list[dict[str, Any]]]:
        """
        获取关键指标的趋势数据（按指标分组）

        Args:
            model_config_id: 模型配置 ID
            key_metrics: 关键指标列表
            days: 获取多少天的数据

        Returns:
            {
                "gsm8k.exact_match": [
                    {"date": "2026-03-20", "value": 0.89, "report_id": 123},
                    ...
                ],
                "ceval-valid.acc": [...]
            }
        """
        trend_data = await self.get_trend_data(model_config_id, days, key_metrics)

        # 按指标重组数据
        result = {metric: [] for metric in key_metrics}

        for data_point in trend_data:
            for metric in key_metrics:
                if metric in data_point["metrics"]:
                    result[metric].append({
                        "date": data_point["date"],
                        "datetime": data_point["datetime"],
                        "value": data_point["metrics"][metric],
                        "report_id": data_point["report_id"],
                        "pass_fail": data_point["pass_fail"]
                    })

        return result

    async def get_pass_fail_history(
        self,
        model_config_id: int,
        days: int = 30
    ) -> list[dict[str, Any]]:
        """
        获取 Pass/Fail 历史记录

        Returns:
            [
                {
                    "date": "2026-03-20",
                    "pass_fail": "pass",
                    "auto_pass_fail": "pass",
                    "manual_override": false,
                    "report_id": 123
                },
                ...
            ]
        """
        cutoff_date = datetime.now(UTC) - timedelta(days=days)

        stmt = (
            select(
                ModelReport.created_at,
                ModelReport.pass_fail,
                ModelReport.auto_pass_fail,
                ModelReport.manual_override,
                ModelReport.id
            )
            .where(ModelReport.model_config_id == model_config_id)
            .where(ModelReport.created_at >= cutoff_date)
            .order_by(ModelReport.created_at.asc())
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            {
                "date": row.created_at.strftime("%Y-%m-%d"),
                "datetime": row.created_at.isoformat(),
                "pass_fail": row.pass_fail,
                "auto_pass_fail": row.auto_pass_fail,
                "manual_override": row.manual_override,
                "report_id": row.id
            }
            for row in rows
        ]

    async def get_comparison_data(
        self,
        report_ids: list[int]
    ) -> list[dict[str, Any]]:
        """
        获取用于对比的报告数据

        Args:
            report_ids: 报告 ID 列表

        Returns:
            报告数据列表
        """
        stmt = (
            select(ModelReport)
            .where(ModelReport.id.in_(report_ids))
            .options(joinedload(ModelReport.model_config))
        )

        result = await self.db.execute(stmt)
        reports = result.scalars().all()

        comparison_data = []
        for report in reports:
            metrics = {}
            if report.metrics_json:
                try:
                    metrics = report.metrics_json  # JSON 字段自动解析为 dict
                    # 兼容旧数据：如果是字符串，手动解析
                    if isinstance(metrics, str):
                        import json
                        metrics = json.loads(metrics)
                except Exception as e:
                    logger.warning(f"Failed to parse metrics_json for report {report.id}: {e}")

            comparison_data.append({
                "id": report.id,
                "model_config_id": report.model_config_id,
                "model_name": report.model_config.model_name if report.model_config else "",
                "date": report.created_at.strftime("%Y-%m-%d %H:%M"),
                "pass_fail": report.pass_fail,
                "auto_pass_fail": report.auto_pass_fail,
                "metrics": metrics,
                "vllm_version": report.vllm_version,
                "hardware": report.hardware,
                "workflow_run_id": report.workflow_run_id,
                "created_at": report.created_at
            })

        return comparison_data

    @staticmethod
    def calculate_changes(
        baseline_metrics: dict[str, Any],
        current_metrics: dict[str, Any]
    ) -> dict[str, Any]:
        """
        计算指标变化

        Args:
            baseline_metrics: 基准指标
            current_metrics: 当前指标

        Returns:
            {
                "metric_name": {
                    "baseline": 0.85,
                    "current": 0.89,
                    "absolute_change": 0.04,
                    "percent_change": 4.7
                },
                ...
            }
        """
        changes = {}

        all_keys = set(baseline_metrics.keys()) | set(current_metrics.keys())

        for key in all_keys:
            baseline_val = baseline_metrics.get(key)
            current_val = current_metrics.get(key)

            change_info = {
                "baseline": baseline_val,
                "current": current_val,
                "absolute_change": None,
                "percent_change": None
            }

            if baseline_val is not None and current_val is not None:
                try:
                    baseline_num = float(baseline_val)
                    current_num = float(current_val)
                    change_info["absolute_change"] = round(current_num - baseline_num, 4)

                    if baseline_num != 0:
                        change_info["percent_change"] = round(
                            (current_num - baseline_num) / baseline_num * 100, 2
                        )
                except (ValueError, TypeError):
                    pass

            changes[key] = change_info

        return changes
