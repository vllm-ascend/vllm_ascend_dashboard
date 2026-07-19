"""Generate a deterministic daily-report preview from the configured database."""
import asyncio
import base64
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.base import SessionLocal, engine
from app.services.daily_report import DailyReportService, _today_shanghai
from app.services.chart_renderer import render_charts
from jinja2 import Environment, FileSystemLoader
from markdown_it import MarkdownIt


def pct(value):
    return f"{float(value or 0):.1f}%"


def build_markdown(data: dict) -> str:
    day = data["report_date"]
    ci = data["yesterday"]["ci"]
    test = data["yesterday"].get("test", {})
    pr = data["yesterday"].get("pr_pipeline", {})
    model = data["yesterday"].get("model", {})
    resource = data["yesterday"].get("resource", {})
    github = data["yesterday"].get("github", {})

    lines = [
        "## 一句话总结",
        f"{day} Nightly A2/A3 实际运行 **{ci['total_cases']}** 个用例，通过 **{ci['passed_cases']}** 个，失败 **{ci['failed_cases']}** 个，整体通过率 **{pct(ci['pass_rate'])}**。",
        "",
        "## 🔧 Nightly 流水线",
        "| 流水线 | 实际运行用例 | 通过 | 失败 | 通过率 |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in ci["by_hardware"]:
        lines.append(
            f"| Nightly {item['hardware']} | {item['total_cases']} | {item['passed_cases']} | "
            f"{item['failed_cases']} | {pct(item['pass_rate'])} |"
        )

    lines += [
        "",
        "## 🧪 测试看板",
        f"报告日期内记录 **{test.get('total_cases', 0)}** 条实际测试结果，通过率 **{pct(float(test.get('pass_rate_7d', 0)) * 100)}**，检测到 flaky 用例 **{test.get('flaky_case_count', 0)}** 个。",
        "",
        "## 📋 PR 流水线",
        f"新增 **{pr.get('recent_opened_count', 0)}** 个 PR，合入 **{pr.get('recent_merged_count', 0)}** 个；当前开放 **{pr.get('open_count', 0)}** 个。",
        "",
        "## 🤖 模型验证",
        f"共产生 **{model.get('total_reports', 0)}** 份报告，通过 **{model.get('pass_count', 0)}**，失败 **{model.get('fail_count', 0)}**，通过率 **{pct(model.get('pass_rate', 0))}**。",
        "",
        "## 📦 项目动态",
        f"PR **{github.get('pr_count', 0)}**，Issue **{github.get('issue_count', 0)}**，Commit **{github.get('commit_count', 0)}**。",
    ]
    clusters = resource.get("clusters", [])
    if clusters:
        lines += ["", "## 🖥️ NPU 资源", "| 集群 | 平均利用率 | NPU 使用 | 执行中 Pod |", "|---|---:|---:|---:|"]
        for cluster in clusters:
            lines.append(
                f"| {cluster['cluster_name']} | {pct(cluster['avg_npu_utilization'])} | "
                f"{cluster['npu_used']}/{cluster['npu_total']} | {cluster['executing_pods']} |"
            )
    lines += [
        "",
        "---",
        f"统计口径：{data['report_window']['start']} 至 {data['report_window']['end']}；时区 {data['timezone']}。跳过、取消及未执行用例不计入 Nightly 通过率。",
    ]
    return "\n".join(lines)


async def main():
    report_date = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else _today_shanghai() - timedelta(days=1)
    try:
        async with SessionLocal() as db:
            service = DailyReportService(db)
            data = await service.generate_report(report_date)
            markdown = build_markdown(data)
            chart_images = render_charts(data)
            env = Environment(
                loader=FileSystemLoader(str(Path(__file__).resolve().parent.parent / "app" / "templates")),
                autoescape=True,
            )
            html = env.get_template("ai_report_email.html").render(
                report_date=data["report_date"],
                ai_report_html=MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown),
                dashboard_url="http://localhost:3000",
                chart_cids=list(chart_images),
            )
            for cid, image in chart_images.items():
                encoded = base64.b64encode(image).decode("ascii")
                html = html.replace(f'src="cid:{cid}"', f'src="data:image/png;base64,{encoded}"')
        output = Path(__file__).resolve().parent.parent / "real_daily_report_preview.html"
        output.write_text(html, encoding="utf-8")
        print(output)
        print(
            f"nightly_total={data['yesterday']['ci']['total_cases']} "
            f"nightly_passed={data['yesterday']['ci']['passed_cases']} "
            f"nightly_failed={data['yesterday']['ci']['failed_cases']} "
            f"nightly_pass_rate={data['yesterday']['ci']['pass_rate']:.1f}"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
