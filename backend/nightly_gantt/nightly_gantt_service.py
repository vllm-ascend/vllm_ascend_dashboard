"""
Nightly 测试用例执行甘特图服务

将 nightly_report.py 脚本的逻辑封装为后端服务：
1. 按 run_number 定位 workflow run（优先查数据库 CIResult，未命中回退 GitHub API 翻页）
2. 拉取该 run 的全部 jobs
3. 过滤基础设施 Job，按 Multi-node / Double-node / Single-node 分类
4. 转换为北京时间，组装甘特图所需结构化数据

数据来源：GitHub Actions API（vllm-project/vllm-ascend 仓库的 nightly workflow）
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.clients.github_client import GitHubClient
from infrastructure.persistence.models import CIResult

logger = logging.getLogger(__name__)

# 北京时区 UTC+8
BJ_TZ = timezone(timedelta(hours=8))

# nightly workflow 配置：hardware key -> (workflow 文件名, 显示名)
NIGHTLY_WORKFLOWS: dict[str, tuple[str, str]] = {
    "a2": ("schedule_nightly_test_a2.yaml", "Nightly-A2"),
    "a3": ("schedule_nightly_test_a3.yaml", "Nightly-A3"),
}

# 基础设施 Job 名称关键词（命中即跳过，只保留用例 Job）
INFRA_KEYWORDS: tuple[str, ...] = (
    "Parse trigger",
    "Export global env",
    "Build nightly",
    "clear-pre-logs",
    "Remove node taints",
    "Merge benchmark",
)

# 阶段分类顺序（用于排序）
PHASE_ORDER: dict[str, int] = {"Multi-node": 0, "Double-node": 1, "Single-node": 2}

# 翻页查找 run_number 的最大页数（每页 100，最多 5000 个 run）
MAX_LOOKUP_PAGES = 50


def classify_job(name: str) -> str | None:
    """按 job 名称前缀分类阶段。

    与 nightly_report.py 的 classify_job 保持一致：
    - multi-node 开头 -> Multi-node
    - double-node 开头 -> Double-node
    - single-node 开头 -> Single-node
    - 其它 -> None（非用例 Job，跳过）
    """
    name_lower = name.lower()
    if name_lower.startswith("multi-node"):
        return "Multi-node"
    if name_lower.startswith("double-node"):
        return "Double-node"
    if name_lower.startswith("single-node"):
        return "Single-node"
    return None


def extract_display_name(name: str) -> str:
    """从 job 名称提取用例展示名。

    job 名称形如 'multi-node (main, DeepSeek-V3_2-W8A8-EP, config.yaml, ...)'，
    取括号内第二个参数作为用例名；若是 pytest 路径则取文件名（去 .py 后缀）。
    与 nightly_report.py 的 extract_display_name 保持一致。
    """
    if "(" not in name:
        return name
    inner = name.split("(", 1)[1].rstrip(")")
    parts = [p.strip() for p in inner.split(",")]
    if len(parts) >= 2:
        candidate = parts[1]
        if "/" in candidate:
            candidate = candidate.rsplit("/", 1)[-1]
            if candidate.endswith(".py"):
                candidate = candidate[:-3]
        return candidate
    return name


def is_infra_job(name: str) -> bool:
    """判断是否为基础设施 Job（按关键词命中，大小写不敏感）。"""
    name_lower = name.lower()
    return any(kw.lower() in name_lower for kw in INFRA_KEYWORDS)


def format_duration(td: timedelta) -> str:
    """timedelta -> 人类可读时长（与 nightly_report.py 的 format_dur 一致）。"""
    total_sec = int(td.total_seconds())
    if total_sec <= 0:
        return "—"
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    if h > 0:
        return f"{h}h{m}m"
    if m > 0:
        return f"{m}m{s}s" if s else f"{m}m"
    return f"{s}s"


def _parse_iso(iso_str: str) -> datetime:
    """解析 GitHub API 返回的 ISO 字符串为带时区的 datetime。"""
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


class NightlyGanttService:
    """Nightly 用例执行甘特图服务。"""

    def __init__(self, db: AsyncSession | None = None, github_client: GitHubClient | None = None):
        self.db = db
        self.github = github_client

    async def get_gantt_data(
        self,
        run_number: int,
        hardware: str = "a3",
    ) -> dict[str, Any]:
        """获取指定 nightly run 的甘特图数据。

        Args:
            run_number: workflow run 编号（GitHub Actions 页面显示的 #号）
            hardware: 硬件类型 'a2' 或 'a3'，默认 'a3'

        Returns:
            甘特图数据字典，包含 run 元信息、KPI、按阶段分组的用例列表

        Raises:
            ValueError: hardware 非法或未配置 GitHub token
            RuntimeError: 未找到 run 或获取 jobs 失败
        """
        hw_key = hardware.lower()
        if hw_key not in NIGHTLY_WORKFLOWS:
            raise ValueError(f"Unsupported hardware: {hardware}, must be one of {list(NIGHTLY_WORKFLOWS)}")

        workflow_file, workflow_display = NIGHTLY_WORKFLOWS[hw_key]

        if not self.github:
            raise RuntimeError("GitHub client not configured (GITHUB_TOKEN missing)")

        # 1. 定位 run_id：优先数据库快路径，未命中回退 GitHub API 翻页
        run_id, run_meta = await self._locate_run(run_number, workflow_file, workflow_display)
        if not run_id:
            raise RuntimeError(f"Run #{run_number} not found for workflow {workflow_file}")

        # 2. 拉取所有 jobs
        all_jobs = await self.github.get_job_list(run_id)
        logger.info(f"Run #{run_number} (id={run_id}) fetched {len(all_jobs)} jobs")

        # 3. 过滤 + 分类 + 组装
        rows = self._build_rows(all_jobs, self.github.owner, self.github.repo)

        # 4. 统计 KPI
        total = len(rows)
        ok_count = sum(1 for r in rows if r["status"] == "ok")
        err_count = total - ok_count
        span_ms = 0
        if rows:
            span_ms = max(r["end_ms"] for r in rows) - min(r["start_ms"] for r in rows)

        phases: dict[str, list[dict[str, Any]]] = {"Multi-node": [], "Double-node": [], "Single-node": []}
        for r in rows:
            phases[r["phase"]].append(r)

        return {
            "run_number": run_number,
            "run_id": run_id,
            "hardware": hardware.upper(),
            "workflow_file": workflow_file,
            "workflow_display": workflow_display,
            "run_meta": run_meta,
            "kpi": {
                "total": total,
                "ok": ok_count,
                "err": err_count,
                "ok_rate": round(ok_count / total, 4) if total else 0.0,
                "err_rate": round(err_count / total, 4) if total else 0.0,
                "span_ms": span_ms,
                "phase_counts": {p: len(items) for p, items in phases.items()},
            },
            "rows": rows,
            "phases": phases,
        }

    async def _locate_run(
        self,
        run_number: int,
        workflow_file: str,
        workflow_display: str,
    ) -> tuple[int | None, dict[str, Any]]:
        """定位 run_id。先查数据库 CIResult（快），未命中调 GitHub API 翻页（慢）。"""
        # 快路径：查数据库
        if self.db is not None:
            try:
                stmt = select(CIResult).where(
                    CIResult.workflow_name == workflow_display,
                    CIResult.run_number == run_number,
                )
                result = await self.db.execute(stmt)
                ci_result = result.scalar_one_or_none()
                if ci_result and ci_result.run_id:
                    logger.info(f"Run #{run_number} hit DB cache: run_id={ci_result.run_id}")
                    return ci_result.run_id, {
                        "status": ci_result.status,
                        "conclusion": ci_result.conclusion,
                        "started_at": ci_result.started_at.isoformat() if ci_result.started_at else None,
                        "completed_at": ci_result.completed_at.isoformat() if ci_result.completed_at else None,
                        "duration_seconds": ci_result.duration_seconds,
                        "html_url": f"https://github.com/{self.github.owner}/{self.github.repo}/actions/runs/{ci_result.run_id}",
                    }
            except Exception as e:
                logger.warning(f"DB lookup failed for run #{run_number}: {e}, fallback to GitHub API")

        # 慢路径：GitHub API 翻页查找
        return await self._locate_run_via_github(run_number, workflow_file)

    async def _locate_run_via_github(
        self,
        run_number: int,
        workflow_file: str,
    ) -> tuple[int | None, dict[str, Any]]:
        """通过 GitHub API 翻页查找匹配 run_number 的 run。未找到返回 (None, {})。"""
        page = 1
        while page <= MAX_LOOKUP_PAGES:
            runs = await self.github.get_workflow_runs(
                workflow_id_or_name=workflow_file,
                per_page=100,
                page=page,
            )
            if not runs:
                break
            for run in runs:
                if run.get("run_number") == run_number:
                    run_id = run["id"]
                    return run_id, {
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "started_at": run.get("created_at"),
                        "completed_at": run.get("updated_at"),
                        "duration_seconds": _calc_run_duration(run),
                        "html_url": run.get("html_url"),
                    }
            page += 1
        return None, {}

    @staticmethod
    def _build_rows(all_jobs: list[dict[str, Any]], owner: str = "vllm-project", repo: str = "vllm-ascend") -> list[dict[str, Any]]:
        """从 GitHub jobs 构造甘特图行：过滤基础设施 + 分类 + 时间转换。"""
        rows: list[dict[str, Any]] = []
        for job in all_jobs:
            name = job.get("name", "")
            if not name:
                continue
            # 跳过基础设施 Job
            if is_infra_job(name):
                continue
            phase = classify_job(name)
            if phase is None:
                continue
            # 跳过 skipped
            if job.get("conclusion") == "skipped":
                continue

            started = job.get("started_at")
            completed = job.get("completed_at")
            if not started or not completed:
                continue

            utc_start = _parse_iso(started)
            utc_end = _parse_iso(completed)
            bj_start = utc_start.astimezone(BJ_TZ)
            bj_end = utc_end.astimezone(BJ_TZ)
            duration = utc_end - utc_start

            rows.append({
                "phase": phase,
                "name": extract_display_name(name),
                "raw_name": name,
                "start_bj": bj_start.strftime("%H:%M:%S"),
                "end_bj": bj_end.strftime("%H:%M:%S"),
                "start_ms": int(utc_start.timestamp() * 1000),
                "end_ms": int(utc_end.timestamp() * 1000),
                "duration": format_duration(duration),
                "duration_seconds": int(duration.total_seconds()),
                "status": "ok" if job.get("conclusion") == "success" else "err",
                "conclusion": job.get("conclusion"),
                "job_id": job.get("id"),
                "job_url": _build_job_url(job.get("id"), job.get("run_id"), owner, repo),
            })

        # 按阶段 + 开始时间排序
        rows.sort(key=lambda r: (PHASE_ORDER.get(r["phase"], 9), r["start_ms"]))
        return rows

    async def close(self):
        """释放 GitHub 客户端资源。"""
        if self.github:
            await self.github.close()


def _calc_run_duration(run: dict[str, Any]) -> int | None:
    """计算 workflow run 时长（秒）。"""
    started = run.get("created_at")
    updated = run.get("updated_at")
    if not started or not updated:
        return None
    try:
        start = _parse_iso(started)
        end = _parse_iso(updated)
        return int((end - start).total_seconds())
    except Exception:
        return None


def _build_job_url(job_id: int | None, run_id: int | None, owner: str = "vllm-project", repo: str = "vllm-ascend") -> str | None:
    """构造 GitHub Job 详情页 URL。owner/repo 默认 vllm-project/vllm-ascend，由调用方传入实际值。"""
    if not job_id or not run_id:
        return None
    return f"https://github.com/{owner}/{repo}/actions/runs/{run_id}/job/{job_id}"
