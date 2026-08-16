"""
模型报告解析服务
解析从 GitHub Actions artifacts 下载的 YAML/JSON 报告文件
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ModelReportParser:
    """模型报告解析服务"""

    def __init__(self):
        pass

    def parse_yaml_report(self, yaml_content: str) -> dict[str, Any]:
        """
        解析 YAML 格式的模型报告

        YAML 格式示例：
        ```yaml
        model_name: "Qwen/Qwen3-8B"
        hardware: "Atlas A2 Series"
        tasks:
          - name: "gsm8k"
            metrics:
              - name: "exact_match,strict-match"
                value: 0.89
              - name: "exact_match,flexible-extract"
                value: 0.85
          - name: "ceval-valid"
            metrics:
              - name: "acc,none"
                value: 0.84
        num_fewshot: 5
        gpu_memory_utilization: 0.6
        tensor_parallel_size: 2
        ```
        """
        try:
            import yaml
            data = yaml.safe_load(yaml_content)
        except Exception as e:
            logger.error(f"Failed to parse YAML report: {e}")
            # 如果 yaml 解析失败，尝试作为 JSON 解析
            try:
                data = json.loads(yaml_content)
            except Exception as json_e:
                logger.error(f"Failed to parse as JSON: {json_e}")
                raise ValueError(f"Invalid YAML/JSON format: {e}")

        return self._normalize_report_data(data)

    def parse_json_report(self, json_content: str) -> dict[str, Any]:
        """
        解析 JSON 格式的 lm_eval 结果

        JSON 格式示例（lm_eval 输出）：
        ```json
        {
          "results": {
            "gsm8k": {
              "exact_match,strict-match": 0.89,
              "exact_match,flexible-extract": 0.85
            },
            "ceval-valid": {
              "acc,none": 0.84
            }
          },
          "config": {
            "model": "Qwen/Qwen3-8B",
            "num_fewshot": 5,
            "batch_size": 1
          }
        }
        ```
        """
        try:
            data = json.loads(json_content)
        except json.JSONDecodeError as e:
            # JSON 解析失败，尝试作为 YAML 解析
            logger.warning(f"JSON parse failed, trying YAML: {e}")
            try:
                import yaml
                data = yaml.safe_load(json_content)
                logger.info("Successfully parsed as YAML")
            except Exception as yaml_e:
                logger.error(f"YAML parse also failed: {yaml_e}")
                raise ValueError(f"Invalid JSON/YAML format. JSON error: {e}. YAML error: {yaml_e}")
        except Exception as e:
            logger.error(f"Failed to parse JSON report: {e}")
            raise ValueError(f"Invalid JSON format: {e}")

        return self._normalize_report_data(data)

    def _normalize_report_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """
        标准化报告数据结构（支持新模板）

        返回统一格式：
        {
            "model_name": str,
            "hardware": str,
            "dtype": str,  # 权重类型
            "features": list,  # 特性列表
            "vllm_version": str,
            "vllm_ascend_version": str,
            "tasks": [...],  # 完整的 tasks 数组
            "serve_cmd": {...},  # 启动命令
            "environment": {...},  # 环境变量
            "metrics": {...},  # 扁平化的 metrics（兼容旧代码）
            "pass_fail": str,  # 总体 pass/fail
            "raw_data": {...}  # 原始数据
        }
        """
        normalized = {
            "model_name": data.get("model_name", data.get("model", "")),
            "hardware": data.get("hardware", ""),
            "dtype": data.get("dtype", ""),
            "features": data.get("feature", []),
            "vllm_version": data.get("vllm_version", ""),
            "vllm_ascend_version": data.get("vllm_ascend_version", ""),
            "tasks": [],
            "serve_cmd": data.get("serve_cmd", {}),
            "environment": data.get("environment", {}),
            "metrics": {},
            "raw_data": data
        }

        # 提取 tasks 和 metrics
        if "tasks" in data and isinstance(data["tasks"], list):
            for task in data["tasks"]:
                task_data = {
                    "name": task.get("name", ""),
                    "metrics": {},
                    "test_input": task.get("test_input", {}),
                    "target": task.get("target", {}),
                    "pass_fail": task.get("pass_fail", "pass")
                }

                # 提取 task 的 metrics
                if "metrics" in task and isinstance(task["metrics"], dict):
                    task_data["metrics"] = task["metrics"]
                    # 扁平化存储到 metrics（兼容旧代码）
                    for metric_name, metric_value in task["metrics"].items():
                        key = f"{task_data['name']}.{metric_name}"
                        normalized["metrics"][key] = metric_value

                normalized["tasks"].append(task_data)

        # 如果是 lm_eval 格式（results 嵌套，旧格式兼容）
        elif "results" in data and isinstance(data["results"], dict):
            for task_name, task_metrics in data["results"].items():
                if isinstance(task_metrics, dict):
                    task_data = {
                        "name": task_name,
                        "metrics": task_metrics,
                        "test_input": {},
                        "target": {},
                        "pass_fail": "pass"  # 旧格式默认 pass
                    }
                    normalized["tasks"].append(task_data)
                    # 扁平化存储
                    for metric_name, metric_value in task_metrics.items():
                        key = f"{task_name}.{metric_name}"
                        normalized["metrics"][key] = metric_value

        # 计算总体 pass_fail（所有 task 都 pass 才算 pass）
        normalized["pass_fail"] = self._calculate_overall_pass_fail(normalized["tasks"])

        return normalized

    def _calculate_overall_pass_fail(self, tasks: list) -> str:
        """
        计算总体 pass_fail

        规则：所有 task 都 pass 才算 pass，否则为 fail
        """
        if not tasks:
            return "pass"

        for task in tasks:
            if task.get("pass_fail", "pass") != "pass":
                return "fail"

        return "pass"

    def evaluate_pass_fail(
        self,
        metrics: dict[str, Any],
        thresholds: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """
        根据阈值评估 Pass/Fail

        Args:
            metrics: 扁平化的 metrics 字典
            thresholds: 阈值配置，格式如：
                {
                    "gsm8k.exact_match,strict-match": 0.85,
                    "ceval-valid.acc,none": 0.80
                }

        Returns:
            (pass_fail, details)
            pass_fail: "pass" 或 "fail"
            details: 评估详情
        """
        if not thresholds:
            return "pass", {"message": "未配置阈值，默认通过"}

        details = {
            "passed_metrics": [],
            "failed_metrics": [],
            "missing_metrics": []
        }

        all_passed = True

        for metric_name, threshold in thresholds.items():
            if metric_name not in metrics:
                details["missing_metrics"].append(metric_name)
                # 缺失的 metrics 视为失败
                all_passed = False
                continue

            actual_value = metrics[metric_name]
            try:
                actual_value = float(actual_value)
                threshold = float(threshold)

                if actual_value >= threshold:
                    details["passed_metrics"].append({
                        "name": metric_name,
                        "actual": actual_value,
                        "threshold": threshold
                    })
                else:
                    details["failed_metrics"].append({
                        "name": metric_name,
                        "actual": actual_value,
                        "threshold": threshold
                    })
                    all_passed = False
            except (ValueError, TypeError) as e:
                logger.warning(f"Failed to compare metric {metric_name}: {e}")
                details["failed_metrics"].append({
                    "name": metric_name,
                    "error": str(e)
                })
                all_passed = False

        pass_fail = "pass" if all_passed else "fail"
        details["pass_fail"] = pass_fail

        return pass_fail, details

    def extract_known_issues(self, report_data: dict[str, Any]) -> str:
        """
        从报告中提取已知问题

        优先级：
        1. known_issues 字段
        2. failed_metrics 自动生成
        3. 空字符串
        """
        issues = []

        # 直接提取 known_issues
        if "known_issues" in report_data and report_data["known_issues"]:
            if isinstance(report_data["known_issues"], str):
                return report_data["known_issues"]
            elif isinstance(report_data["known_issues"], list):
                return "\n".join(f"- {issue}" for issue in report_data["known_issues"])

        # 从失败的 metrics 生成
        metrics = report_data.get("metrics", {})
        thresholds = report_data.get("thresholds", {})

        if thresholds:
            pass_fail, details = self.evaluate_pass_fail(metrics, thresholds)
            if pass_fail == "fail":
                for failed in details.get("failed_metrics", []):
                    if "name" in failed:
                        issues.append(
                            f"指标 '{failed['name']}' 未达到阈值 "
                            f"(实际：{failed.get('actual', 'N/A')}, "
                            f"阈值：{failed.get('threshold', 'N/A')})"
                        )
                for missing in details.get("missing_metrics", []):
                    issues.append(f"缺少指标数据：{missing}")

        return "\n".join(issues) if issues else ""
