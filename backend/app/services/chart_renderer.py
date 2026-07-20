"""
邮件报告图表渲染模块

用 matplotlib (Agg backend) 将 report_data 画成 PNG 图表，
通过 CID（Content-ID）内嵌附件方式嵌入邮件 HTML。

每个图表函数独立，单个失败不影响其他。
"""
from __future__ import annotations

import logging
from io import BytesIO

import matplotlib
matplotlib.use("Agg")  # 非交互式后端，必须在 import pyplot 之前

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 全局样式
# ---------------------------------------------------------------------------

# 与前端 Recharts 一致的色板
BLUE = "#1890ff"
GREEN = "#2fc25b"
YELLOW = "#facc14"
RED = "#dc2626"
GREY = "#94a3b8"
DARK = "#1e293b"
BG = "#f8fafc"

COLORS = [BLUE, GREEN, YELLOW, RED]

# 中文字体设置
CN_FONT = "Microsoft YaHei"
_FALLBACK_FONTS = ["SimHei", "Noto Sans CJK SC", "sans-serif"]

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": [CN_FONT] + _FALLBACK_FONTS,
    "axes.unicode_minus": False,
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.15,
})

WINDOW_LABELS = {"yesterday": "昨日", "last_week": "近一周", "last_month": "近一月"}


def _fig_to_bytes(fig: plt.Figure) -> bytes:
    """将 matplotlib Figure 渲染为 PNG bytes（关闭 figure 释放内存）。"""
    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _safe_render(cid: str, render_fn) -> tuple[str, bytes] | None:
    """安全调用单个图表渲染函数，异常时记录日志并返回 None。"""
    try:
        return (cid, render_fn())
    except Exception:
        logger.warning("Failed to render chart %s", cid, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 公开入口
# ---------------------------------------------------------------------------

def render_charts(report_data: dict) -> dict[str, bytes]:
    """将 report_data 渲染为一组 PNG 图表。

    Returns:
        dict[str, bytes]  如 {"ci_trend": b"...", "model_pass_rate": b"...", ...}
        渲染失败的图表会被跳过，不会出现在返回 dict 中。
    """
    results = [
        _safe_render("nightly_case_pass_rate", lambda: _render_nightly_case_pass_rate(report_data)),
        _safe_render("ci_trend", lambda: _render_ci_trend(report_data)),
        _safe_render("model_pass_rate", lambda: _render_model_pass_rate(report_data)),
        _safe_render("pr_pipeline", lambda: _render_pr_pipeline(report_data)),
        _safe_render("npu_utilization", lambda: _render_npu_utilization(report_data)),
    ]
    return {cid: data for cid, data in results if data is not None}


# ---------------------------------------------------------------------------
# 单图渲染函数
# ---------------------------------------------------------------------------

def _render_nightly_case_pass_rate(report_data: dict) -> bytes:
    """Compare executed/pass/fail test cases and pass rates for Nightly A2/A3."""
    stats = report_data.get("yesterday", {}).get("ci", {}).get("by_hardware", [])
    by_hardware = {item.get("hardware"): item for item in stats}
    rows = [by_hardware.get(hw, {"hardware": hw}) for hw in ("A2", "A3")]
    passed = [int(item.get("passed_cases", 0)) for item in rows]
    failed = [int(item.get("failed_cases", 0)) for item in rows]
    rates = [float(item.get("pass_rate", 0)) for item in rows]

    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    x = list(range(len(rows)))
    width = 0.52
    pass_bars = ax.bar(x, passed, width, color=GREEN, label="Passed", zorder=3)
    fail_bars = ax.bar(x, failed, width, bottom=passed, color=RED, label="Failed", zorder=3)
    max_total = max([p + f for p, f in zip(passed, failed)] + [1])
    for idx, (pass_bar, fail_bar, rate) in enumerate(zip(pass_bars, fail_bars, rates)):
        total = passed[idx] + failed[idx]
        center = pass_bar.get_x() + pass_bar.get_width() / 2
        if total == 0:
            ax.text(center, max_total * 0.06, "No executed cases", ha="center", va="bottom",
                    fontsize=9, color=GREY, fontstyle="italic")
            continue
        ax.text(center, total + max_total * 0.045, f"Pass rate {rate:.1f}%",
                ha="center", va="bottom", fontsize=10, color=DARK, fontweight="bold")
        if passed[idx]:
            ax.text(center, passed[idx] / 2, f"{passed[idx]} passed",
                    ha="center", va="center", fontsize=9, color="white", fontweight="bold")
        if failed[idx]:
            ax.text(center, passed[idx] + failed[idx] / 2, f"{failed[idx]} failed",
                    ha="center", va="center", fontsize=9, color="white", fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(["Nightly A2", "Nightly A3"], fontsize=10)
    ax.set_ylabel("Executed test cases", fontsize=10, color=DARK)
    ax.set_title("Nightly A2/A3 Test Case Pass Rate", fontsize=13, fontweight="bold", color=DARK, pad=16)
    ax.set_ylim(0, max_total * 1.22)
    ax.grid(axis="y", alpha=0.25, zorder=0)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2,
              fontsize=9, frameon=False)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return _fig_to_bytes(fig)


def _render_ci_trend(report_data: dict) -> bytes:
    """CI 通过率趋势：三个时间窗口的通过率 + 总运行数（双轴柱状图）。"""
    windows = ["yesterday", "last_week", "last_month"]
    labels = [WINDOW_LABELS[w] for w in windows]

    rates = []
    totals = []
    for w in windows:
        ci = report_data.get(w, {}).get("ci", {})
        rates.append(ci.get("success_rate", 0))
        totals.append(ci.get("total_runs", 0))

    fig, ax1 = plt.subplots(figsize=(6, 3))
    ax1.set_facecolor("white")
    fig.patch.set_facecolor("white")

    x = range(len(labels))
    bars = ax1.bar(x, rates, color=BLUE, alpha=0.85, width=0.5, zorder=3)
    ax1.set_ylabel("通过率 (%)", color=DARK, fontsize=10)
    ax1.set_ylim(0, max(max(rates) * 1.25, 100))
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, fontsize=10)
    ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))

    # 在柱子上标注数值
    for bar, rate in zip(bars, rates):
        ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                 f"{rate:.1f}%", ha="center", va="bottom", fontsize=9, color=DARK)

    # 右轴：总运行数
    ax2 = ax1.twinx()
    ax2.plot(x, totals, color=GREEN, marker="o", linewidth=2, markersize=6, zorder=4)
    ax2.set_ylabel("总运行数", color=GREEN, fontsize=10)
    ax2.tick_params(axis="y", labelcolor=GREEN)
    if totals:
        ax2.set_ylim(0, max(max(totals) * 1.3, 1))

    ax1.set_title("CI 通过率趋势", fontsize=13, fontweight="bold", color=DARK, pad=12)
    ax1.grid(axis="y", alpha=0.3, zorder=0)
    ax1.set_axisbelow(True)

    fig.tight_layout()
    return _fig_to_bytes(fig)


def _render_model_pass_rate(report_data: dict) -> bytes:
    """模型验证通过率：三个时间窗口对比（折线 + 柱状图）。"""
    windows = ["yesterday", "last_week", "last_month"]
    labels = [WINDOW_LABELS[w] for w in windows]

    rates = []
    pass_counts = []
    fail_counts = []
    for w in windows:
        m = report_data.get(w, {}).get("model", {})
        rates.append(m.get("pass_rate", 0))
        pass_counts.append(m.get("pass_count", 0))
        fail_counts.append(m.get("fail_count", 0))

    fig, ax = plt.subplots(figsize=(6, 3))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    x = range(len(labels))
    width = 0.3
    ax.bar([i - width / 2 for i in x], pass_counts, width, color=GREEN, alpha=0.85,
           label="Pass", zorder=3)
    ax.bar([i + width / 2 for i in x], fail_counts, width, color=RED, alpha=0.85,
           label="Fail", zorder=3)

    # 折线：通过率
    ax2 = ax.twinx()
    ax2.plot(x, rates, color=BLUE, marker="D", linewidth=2.2, markersize=7,
             label="通过率", zorder=4)
    ax2.set_ylabel("通过率 (%)", color=BLUE, fontsize=10)
    ax2.tick_params(axis="y", labelcolor=BLUE)
    ax2.set_ylim(0, max(max(rates) * 1.2, 100))
    for i, rate in enumerate(rates):
        ax2.text(i, rate + 2, f"{rate:.1f}%", ha="center", va="bottom",
                 fontsize=9, color=BLUE, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("模型数", fontsize=10, color=DARK)
    ax.set_title("模型验证通过率", fontsize=13, fontweight="bold", color=DARK, pad=12)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.8)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)

    fig.tight_layout()
    return _fig_to_bytes(fig)


def _render_pr_pipeline(report_data: dict) -> bytes:
    """PR 流水线概况：打开/合并/关闭数量 + backlog 指标。"""
    pr = report_data.get("yesterday", {}).get("pr_pipeline", {})
    if not pr:
        # 返回空状态图
        fig, ax = plt.subplots(figsize=(6, 2.5))
        ax.text(0.5, 0.5, "暂无 PR 流水线数据", ha="center", va="center",
                fontsize=12, color=GREY, transform=ax.transAxes)
        ax.axis("off")
        return _fig_to_bytes(fig)

    categories = ["打开", "合并", "关闭"]
    values = [
        pr.get("recent_opened_count", 0) or pr.get("open_count", 0),
        pr.get("recent_merged_count", 0) or pr.get("merged_count", 0),
        pr.get("closed_count", 0),
    ]
    colors = [BLUE, GREEN, GREY]

    fig, ax = plt.subplots(figsize=(6, 3))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    bars = ax.bar(categories, values, color=colors, alpha=0.85, width=0.5, zorder=3)
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.02,
                str(val), ha="center", va="bottom", fontsize=11, fontweight="bold", color=DARK)

    # 右侧文本标注 backlog 和 merge_rate
    info_lines = []
    merge_rate = pr.get("merge_rate")
    if merge_rate is not None:
        info_lines.append(f"合并率: {merge_rate:.1f}%")
    avg_time = pr.get("avg_time_to_merge_hours")
    if avg_time is not None:
        info_lines.append(f"平均合并: {avg_time:.1f}h")
    backlog = pr.get("backlog_index")
    if backlog is not None:
        info_lines.append(f"Backlog: {backlog:.0f} ({pr.get('backlog_level', '-')})")

    if info_lines:
        ax.text(0.98, 0.88, "\n".join(info_lines), transform=ax.transAxes,
                fontsize=9, color=DARK, ha="right", va="top",
                bbox={"boxstyle": "round,pad=0.4", "facecolor": BG, "edgecolor": "#e5e7eb"})

    ax.set_title("PR 流水线 (昨日)", fontsize=13, fontweight="bold", color=DARK, pad=12)
    ax.grid(axis="y", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(axis="x", labelsize=10)

    fig.tight_layout()
    return _fig_to_bytes(fig)


def _render_npu_utilization(report_data: dict) -> bytes:
    """各集群 NPU 利用率（横向柱状图）。"""
    clusters = report_data.get("yesterday", {}).get("resource", {}).get("clusters", [])
    if not clusters:
        fig, ax = plt.subplots(figsize=(6, 2.5))
        ax.text(0.5, 0.5, "暂无 NPU 资源数据", ha="center", va="center",
                fontsize=12, color=GREY, transform=ax.transAxes)
        ax.axis("off")
        return _fig_to_bytes(fig)

    names = [c.get("cluster_name", "?") for c in clusters]
    utils = [c.get("avg_npu_utilization", 0) for c in clusters]

    # 按利用率排序
    sorted_pairs = sorted(zip(utils, names), key=lambda x: x[0])
    utils_sorted, names_sorted = zip(*sorted_pairs) if sorted_pairs else ([], [])

    # 根据利用率着色
    bar_colors = []
    for u in utils_sorted:
        if u >= 70:
            bar_colors.append(RED)
        elif u >= 40:
            bar_colors.append(YELLOW)
        else:
            bar_colors.append(GREEN)

    fig, ax = plt.subplots(figsize=(6, max(2.5, len(names) * 0.55)))
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    y_pos = range(len(names_sorted))
    bars = ax.barh(y_pos, utils_sorted, color=bar_colors, alpha=0.85, height=0.55, zorder=3)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(names_sorted, fontsize=9)
    ax.set_xlabel("NPU 利用率 (%)", fontsize=10, color=DARK)
    ax.set_xlim(0, max(max(utils_sorted) * 1.2, 100) if utils_sorted else 100)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%.0f%%"))

    for bar, u in zip(bars, utils_sorted):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{u:.1f}%", va="center", fontsize=9, fontweight="bold",
                color=DARK)

    ax.set_title("NPU 利用率 (各集群 · 昨日)", fontsize=13, fontweight="bold",
                 color=DARK, pad=12)
    ax.grid(axis="x", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)
    ax.invert_yaxis()

    fig.tight_layout()
    return _fig_to_bytes(fig)
