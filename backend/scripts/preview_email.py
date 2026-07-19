"""
本地邮件预览工具：生成带图表的邮件 HTML，base64 内嵌图片，浏览器可直接打开。

Usage:
    cd backend
    python scripts/preview_email.py           # 使用 mock 数据
    python scripts/preview_email.py --real    # 从数据库拉真实数据（需要 DB 连接）
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

# 确保 backend 根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import markdown as md_lib
from jinja2 import Environment, FileSystemLoader

from app.services.chart_renderer import render_charts

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"
OUTPUT_FILE = Path(__file__).resolve().parent.parent / "debug_email_preview.html"


def _build_mock_data() -> dict:
    """构造模拟 report_data，覆盖有数据和无数据两种场景。"""
    return {
        "report_date": "2026-07-17",
        "yesterday": {
            "ci": {
                "total_runs": 42, "success_runs": 38, "failure_runs": 4,
                "success_rate": 90.5, "avg_duration_seconds": 1234,
                "failed_workflows": [
                    {"workflow_name": "nightly-build", "run_number": 128,
                     "duration_seconds": 3600, "hardware": "910B"},
                    {"workflow_name": "unit-tests", "run_number": 456,
                     "duration_seconds": 1200, "hardware": "910B"},
                ],
            },
            "model": {
                "total_reports": 15, "pass_count": 12, "fail_count": 3,
                "pass_rate": 80.0,
                "new_models": ["Qwen3-8B", "DeepSeek-V3"],
                "failed_models": [
                    {"model_name": "Llama-3-70B", "hardware": "910B", "vllm_version": "v0.8.0"},
                    {"model_name": "Mistral-Large", "hardware": "910B", "vllm_version": "v0.8.0"},
                ],
            },
            "github": {
                "pr_count": 8, "issue_count": 12, "commit_count": 24,
                "ai_summary_snippet": "昨日社区活跃度较高，新增3个PR合入。",
            },
            "performance": {
                "avg_throughput": 1250.5, "avg_p50_latency": 45.2, "avg_p99_latency": 180.6,
            },
            "pr_pipeline": {
                "open_count": 8, "merged_count": 5, "closed_count": 2,
                "recent_opened_count": 3, "recent_merged_count": 4,
                "merge_rate": 55.6, "avg_time_to_merge_hours": 4.2,
                "backlog_index": 12, "backlog_level": "normal",
            },
            "resource": {
                "clusters": [
                    {"cluster_name": "bj-cluster-910b", "avg_npu_utilization": 72.3,
                     "npu_total": 64, "npu_used": 46, "executing_pods": 18},
                    {"cluster_name": "sh-cluster-910b", "avg_npu_utilization": 45.1,
                     "npu_total": 128, "npu_used": 58, "executing_pods": 22},
                    {"cluster_name": "gz-cluster-910b", "avg_npu_utilization": 88.7,
                     "npu_total": 32, "npu_used": 28, "executing_pods": 12},
                    {"cluster_name": "cd-cluster-910b", "avg_npu_utilization": 31.2,
                     "npu_total": 64, "npu_used": 20, "executing_pods": 8},
                ],
            },
            "test": {
                "health_score": {"overall": 85, "stability": 90, "coverage": 78},
                "total_cases": 320, "pass_rate_7d": 94.5, "flaky_case_count": 3,
            },
            "diagnosis_stats": {
                "yesterday_count": 5, "total_count": 245, "liked_count": 180,
            },
        },
        "last_week": {
            "ci": {"total_runs": 280, "success_runs": 245, "failure_runs": 35,
                   "success_rate": 87.5, "avg_duration_seconds": 1180},
            "model": {"total_reports": 95, "pass_count": 80, "fail_count": 15,
                      "pass_rate": 84.2},
            "github": {"pr_count": 45, "issue_count": 67, "commit_count": 156},
            "performance": {"avg_throughput": 1180.3, "avg_p50_latency": 48.1,
                            "avg_p99_latency": 195.2},
        },
        "last_month": {
            "ci": {"total_runs": 1200, "success_runs": 1080, "failure_runs": 120,
                   "success_rate": 90.0, "avg_duration_seconds": 1150},
            "model": {"total_reports": 400, "pass_count": 350, "fail_count": 50,
                      "pass_rate": 87.5},
            "github": {"pr_count": 180, "issue_count": 280, "commit_count": 620},
            "performance": {"avg_throughput": 1150.8, "avg_p50_latency": 50.3,
                            "avg_p99_latency": 210.5},
        },
    }


_MOCK_AI_REPORT = """\
## 一句话总结
昨日 vLLM Ascend 社区运行整体平稳，Nightly CI 通过率 90.5%，模型验证通过率 80%，PR 流水线合并率 55.6%。需关注 Llama-3-70B 和 Mistral-Large 模型验证失败问题。

## 整体健康度
- **CI 状态**: 健康（通过率 90.5%，近一周 87.5%，近一月 90.0%）
- **模型验证**: 关注（昨日通过率 80.0%，低于近一月均值 87.5%）
- **NPU 资源**: 关注（gz-cluster 利用率 88.7%，接近瓶颈）

## Nightly 流水线
昨日共执行 **42** 次 Nightly CI 运行，通过 **38** 次（90.5%），失败 **4** 次。
失败流水线：
- `nightly-build` (run #128)：构建超时，耗时 3600s
- `unit-tests` (run #456)：4 个测试用例失败，硬件 910B

## PR 流水线
昨日新增 **3** 个 PR，合并 **4** 个，关闭 **2** 个。合并率 **55.6%**，平均合并耗时 **4.2h**。Backlog 指数 **12**（normal 水平）。

## 项目动态
- 新增模型验证：**Qwen3-8B**、**DeepSeek-V3** 首次进入验证矩阵
- GitHub 活跃：昨日 **8** PR + **12** Issue + **24** Commit
- 测试看板：**320** 用例，7日通过率 **94.5%**，flaky 用例 **3** 个

## 风险与待办
1. `Llama-3-70B` 和 `Mistral-Large` 在 910B 上持续失败，需排查是否为驱动兼容性问题
2. `gz-cluster-910b` NPU 利用率达 **88.7%**，建议扩容或错峰调度
3. flaky 用例 3 个，影响测试稳定性，建议加入 quarantine
"""


def main():
    use_real = "--real" in sys.argv

    if use_real:
        print("Real data mode not implemented yet. Use mock data with: python scripts/preview_email.py")
        return

    report_data = _build_mock_data()
    ai_report_md = _MOCK_AI_REPORT
    ai_report_html = md_lib.markdown(ai_report_md, extensions=["tables", "fenced_code"])

    # Render charts
    chart_images = render_charts(report_data)
    chart_cids = list(chart_images.keys())
    print(f"Charts rendered: {chart_cids}")

    # Build base64 map for local preview
    chart_base64 = {cid: base64.b64encode(data).decode() for cid, data in chart_images.items()}

    # Render email HTML
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("ai_report_email.html")
    html = template.render(
        report_date=report_data["report_date"],
        ai_report_html=ai_report_html,
        dashboard_url="http://localhost:3000",
        chart_cids=chart_cids,
    )

    # Replace cid: references with base64 for local browser viewing
    for cid, b64 in chart_base64.items():
        html = html.replace(f'src="cid:{cid}"', f'src="data:image/png;base64,{b64}"')

    OUTPUT_FILE.write_text(html, encoding="utf-8")
    print(f"Preview saved: {OUTPUT_FILE} ({len(html)} chars)")
    print("Open this file in a browser to inspect the email.")


if __name__ == "__main__":
    main()
