"""
Agent 安全工具集

为 Smolagents ToolCallingAgent 提供工具函数。
所有工具通过 smolagents @tool 装饰器注册，LLM 通过 function calling 调用。

安全原则：
  - 路径限制在 data/ 目录内
  - 网络请求仅允许 GitHub API 域名
  - 没有 shell / exec / write / delete
  - 所有返回值有长度上限，防止 token 爆炸
"""
import contextvars
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
from smolagents import tool

from app.core.config import settings
from app.services.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

# ContextVar：每个 agent run 拥有独立的上下文，并发安全
_ctx_memory_manager: contextvars.ContextVar[MemoryManager | None] = (
    contextvars.ContextVar("memory_manager", default=None)
)
_ctx_github_token: contextvars.ContextVar[str] = (
    contextvars.ContextVar("github_token", default="")
)


def set_tool_context(
    memory_manager: MemoryManager,
    github_token: str = "",
) -> tuple[contextvars.Token, contextvars.Token]:
    """在 Agent 运行前注入运行时上下文（并发安全）"""
    return (
        _ctx_memory_manager.set(memory_manager),
        _ctx_github_token.set(github_token or settings.GITHUB_TOKEN),
    )


def reset_tool_context(tokens: tuple[contextvars.Token, contextvars.Token]) -> None:
    """Restore the previous context after an agent run."""
    memory_token, github_token = tokens
    _ctx_memory_manager.reset(memory_token)
    _ctx_github_token.reset(github_token)


def _get_memory_manager() -> MemoryManager | None:
    return _ctx_memory_manager.get(None)


def _get_github_token() -> str:
    return _ctx_github_token.get("") or settings.GITHUB_TOKEN


def _safe_data_path(path: str) -> Path:
    """
    安全地将用户提供的路径解析到 data/ 目录下。

    拒绝包含路径穿越的输入。
    """
    if not isinstance(path, str) or "\x00" in path:
        raise ValueError("invalid path")
    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError(f"不允许的路径: {path}")
    data_dir = Path(settings.DATA_DIR)
    if not data_dir.is_absolute():
        data_dir = Path.cwd() / data_dir
    data_dir = data_dir.resolve()
    resolved = (data_dir / candidate).resolve()
    try:
        resolved.relative_to(data_dir)
    except ValueError:
        raise ValueError(f"路径穿越被阻止: {path}") from None
    return resolved


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def read_log_file(path: str) -> str:
    """读取 CI 日志或其他数据文件的内容。

    Args:
        path: 文件相对于 data/ 目录的路径，例如 "claude_logs/2026-07-01/analysis.log"
    """
    try:
        full_path = _safe_data_path(path)
    except ValueError as e:
        return f"Error: {e}"

    if not full_path.exists():
        return f"Error: 文件不存在: {path}"
    if not full_path.is_file():
        return f"Error: 不是文件: {path}"

    try:
        if full_path.stat().st_size > 5 * 1024 * 1024:
            return "Error: file is too large to read (limit: 5 MiB)"
        content = full_path.read_text(encoding="utf-8", errors="replace")
        max_len = 50000
        if len(content) > max_len:
            content = content[:max_len] + f"\n\n... (截断，共 {len(content)} 字符)"
        return content
    except Exception as e:
        return f"Error: 读取文件失败: {e}"


@tool
def grep_content(pattern: str, path: str) -> str:
    """在指定文件中搜索匹配 pattern 的行。类似 grep 命令。

    Args:
        pattern: 搜索模式（支持正则表达式）
        path: 文件相对于 data/ 目录的路径
    """
    if not pattern or len(pattern) > 200:
        return "Error: search pattern must contain 1-200 characters"
    try:
        full_path = _safe_data_path(path)
    except ValueError as e:
        return f"Error: {e}"

    if not full_path.exists():
        return f"Error: 文件不存在: {path}"

    try:
        if full_path.stat().st_size > 5 * 1024 * 1024:
            return "Error: file is too large to search (limit: 5 MiB)"
        content = full_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        matched = []
        for i, line in enumerate(lines, 1):
            # Literal matching avoids catastrophic backtracking because
            # Python's regex engine has no execution timeout.
            if pattern in line:
                matched.append(f"{i}: {line[:200]}")

        if not matched:
            return f"未找到匹配 '{pattern}' 的行"
        if len(matched) > 100:
            return "\n".join(matched[:100]) + f"\n\n... (共 {len(matched)} 行匹配，仅显示前 100 行)"
        return "\n".join(matched)
    except Exception as e:
        return f"Error: 搜索失败: {e}"


@tool
def search_memory(query: str, memory_type: str = "failure_analysis") -> str:
    """搜索历史分析记忆。

    Args:
        query: 搜索关键词或描述
        memory_type: 记忆类型，可选 failure_analysis / daily_summary / commit_analysis
    """
    mm = _get_memory_manager()
    if mm is None:
        return "Error: 记忆管理器未初始化"

    try:
        results = mm.recall_sync(
            query=query,
            memory_type=memory_type,
            limit=5,
        )
    except Exception as e:
        return f"Error: 搜索记忆失败: {e}"

    if not results:
        return f"未找到与 '{query}' 相关的历史记录"

    formatted = MemoryManager.format_memories_for_prompt(results)
    return formatted


@tool
def fetch_github_api(url: str) -> str:
    """调用 GitHub REST API。

    Args:
        url: GitHub API URL，例如 https://api.github.com/repos/vllm-project/vllm-ascend/issues/42
    """
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return "Error: invalid GitHub API port"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.github.com"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
    ):
        return f"Error: 仅允许 api.github.com 域名，不支持: {parsed.netloc}"

    token = _get_github_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        import asyncio

        async def _fetch():
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=headers)
                return resp

        response = asyncio.run(_fetch())
        if response.status_code == 200:
            data = response.json()
            # 截断过大的响应
            text = json.dumps(data, ensure_ascii=False, indent=2)
            if len(text) > 10000:
                text = text[:10000] + "\n\n... (截断)"
            return text
        return f"GitHub API 返回 {response.status_code}: {response.text[:500]}"
    except Exception as e:
        return f"Error: GitHub API 调用失败: {e}"


@tool
def list_files(directory: str = "") -> str:
    """列出 data/ 目录下的文件和子目录。

    Args:
        directory: data/ 下的子目录路径，留空列出根目录
    """
    try:
        target = _safe_data_path(directory or ".")
    except ValueError as e:
        return f"Error: {e}"

    if not target.exists():
        return f"Error: 目录不存在: {directory}"
    if not target.is_dir():
        return f"Error: 不是目录: {directory}"

    try:
        items = []
        for item in sorted(target.iterdir()):
            suffix = "/" if item.is_dir() else ""
            items.append(f"  {item.name}{suffix}")
        if not items:
            return f"目录为空: {directory or 'data/'}"
        if len(items) > 200:
            return f"data/{directory}/\n" + "\n".join(items[:200]) + f"\n\n... (共 {len(items)} 项，仅显示前 200 项)"
        return f"data/{directory}/\n" + "\n".join(items)
    except Exception as e:
        return f"Error: 列出文件失败: {e}"


# ---------------------------------------------------------------------------
# 工具集
# ---------------------------------------------------------------------------

# CI 失败分析工具集
FAILURE_ANALYSIS_TOOLS = [
    read_log_file,
    grep_content,
    search_memory,
    fetch_github_api,
    list_files,
]

# 每日总结 / Commit 分析工具集（数据通常在 prompt 内，工具较少）
SUMMARY_TOOLS = [
    search_memory,
    fetch_github_api,
]
