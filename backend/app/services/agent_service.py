"""
Agent Service — Smolagents ToolCallingAgent 封装层

替换 Claude Code CLI 的 subprocess 调用方式，使用 Smolagents 框架
的 ToolCallingAgent 实现 ReAct agent loop。

架构：
  AgentService.run()
    → MemoryManager.recall() 检索历史记忆
    → SkillRegistry 加载 system prompt
    → LiteLLMModel 对接 LLM
    → ToolCallingAgent 执行 ReAct
    → MemoryManager.memorize() 存储结果
"""
import asyncio
import logging
import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from smolagents import LiteLLMModel, ToolCallingAgent

from app.services.agent_tools import (
    FAILURE_ANALYSIS_TOOLS,
    SUMMARY_TOOLS,
    reset_tool_context,
    set_tool_context,
)
from app.services.memory_manager import MemoryManager, MemoryRecord
from app.services.skill_registry import SkillRegistry, get_skill_registry

logger = logging.getLogger(__name__)

# LiteLLM model prefix mapping（与 litellm_sync.py 保持一致）
_PROVIDER_PREFIX = {
    "openai": "openai",
    "qwen": "openai",
    "anthropic": "anthropic",
    "deepseek": "deepseek",
    "zhipu": "openai",
    "glm": "openai",
}


def _detect_prefix(provider: str, api_base: str) -> str:
    """推测 LiteLLM model prefix"""
    base_lower = (api_base or "").lower()
    if "deepseek" in base_lower:
        return "deepseek"
    if any(k in base_lower for k in ("bigmodel", "zhipu", "dashscope", "aliyuncs", "openai")):
        return "openai"
    if "anthropic" in base_lower:
        return "anthropic"
    return _PROVIDER_PREFIX.get(provider, "openai")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AgentTask:
    """一次 Agent 任务的配置"""
    prompt: str
    provider_config: dict  # {provider, api_key, api_base_url, default_model}
    skill_scope: str = ""  # SkillRegistry scope，如 "ci_failure_analysis"
    system_prompt: str = ""  # 如果提供，优先于 skill_scope
    max_steps: int = 20
    timeout_seconds: float = 1800
    memory_type: str = ""  # 记忆类型
    memory_filters: dict | None = None  # 记忆元数据过滤
    source_id: int | None = None  # 关联的业务记录 ID
    work_dir: str | None = None  # 工作目录（暂未使用，预留）


@dataclass
class AgentResult:
    """Agent 任务结果"""
    content: str
    steps: int = 0
    duration_seconds: float = 0.0
    model_used: str = ""
    exit_code: int = 0
    error_message: str = ""
    memory_id: int | None = None


class AgentServiceError(Exception):
    """Agent 服务异常"""
    pass


# ---------------------------------------------------------------------------
# AgentService
# ---------------------------------------------------------------------------


class AgentService:
    """
    Agent 服务 — Smolagents 封装层。

    用法:
        agent_svc = AgentService(db)
        result = await agent_svc.run(AgentTask(
            prompt="分析这个 CI 失败...",
            provider_config={...},
            skill_scope="ci_failure_analysis",
            memory_type="failure_analysis",
        ))
    """

    DEFAULT_MAX_STEPS = 20
    DEFAULT_TIMEOUT_SECONDS = 1800

    def __init__(self, db):
        self.db = db
        self.memory = MemoryManager(db)
        self.skill_registry: SkillRegistry = get_skill_registry()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self, task: AgentTask) -> AgentResult:
        """
        执行一次 Agent 任务。

        Args:
            task: 任务配置

        Returns:
            AgentResult 包含输出内容、步数、耗时等
        """
        validation_error = self._validate_task(task)
        if validation_error:
            return AgentResult(content="", exit_code=2, error_message=validation_error)

        provider = task.provider_config.get("provider", "openai").lower()
        model = task.provider_config.get("default_model", "claude-sonnet-4-20250514")
        api_key = task.provider_config.get("api_key", "")
        api_base = task.provider_config.get("api_base_url", "")
        max_steps = task.max_steps or self.DEFAULT_MAX_STEPS
        litellm_proxy = os.environ.get("LITELLM_PROXY_URL", "").strip()
        proxy_only = os.environ.get("AGENT_PROXY_ONLY", "").lower() in ("1", "true", "yes")

        if proxy_only and not litellm_proxy:
            return AgentResult(
                content="",
                model_used=model,
                exit_code=2,
                error_message="Agent proxy-only mode requires LITELLM_PROXY_URL",
            )
        if proxy_only:
            proxy_url = urlparse(litellm_proxy)
            allowed_proxy_hosts = {
                host.strip().lower()
                for host in os.environ.get(
                    "AGENT_PROXY_ALLOWED_HOSTS",
                    "litellm,vllm-dashboard-litellm,vllm-litellm-dev",
                ).split(",")
                if host.strip()
            }
            if (
                proxy_url.scheme not in {"http", "https"}
                or not proxy_url.hostname
                or proxy_url.hostname.lower() not in allowed_proxy_hosts
            ):
                return AgentResult(
                    content="",
                    model_used=model,
                    exit_code=2,
                    error_message="Agent proxy-only mode requires a container-network proxy URL",
                )
            if not os.environ.get("LITELLM_MASTER_KEY", ""):
                return AgentResult(
                    content="",
                    model_used=model,
                    exit_code=2,
                    error_message="Agent proxy-only mode requires LITELLM_MASTER_KEY",
                )

        start = time.monotonic()

        # 1. 检索历史记忆
        memories = []
        if task.memory_type:
            try:
                memories = await self.memory.recall(
                    query=task.prompt,
                    memory_type=task.memory_type,
                    filters=task.memory_filters,
                    limit=5,
                )
                if memories:
                    logger.info(
                        "AgentService: recalled %d memories for type=%s",
                        len(memories), task.memory_type,
                    )
            except Exception as e:
                logger.warning("AgentService: memory recall failed: %s", e)

        # 2. 构建 system prompt
        system_prompt = self._build_system_prompt(
            skill_scope=task.skill_scope,
            fallback_prompt=task.system_prompt,
            memories=memories,
        )

        # 3. 选择工具集
        tools = self._select_tools(task)

        # 4. 注入运行时上下文（DB session、token 等）
        context_tokens = set_tool_context(
            memory_manager=self.memory,
            github_token=os.environ.get("GITHUB_TOKEN", ""),
        )

        # 5. 创建模型和 Agent
        # A LiteLLM proxy exposes an OpenAI-compatible endpoint regardless of
        # the upstream provider registered behind the model alias.
        prefix = "openai" if litellm_proxy else _detect_prefix(provider, api_base)
        model_id = f"{prefix}/{model}"

        lite_kwargs = {
            "model_id": model_id,
            "api_key": api_key,
        }
        if api_base:
            lite_kwargs["api_base"] = api_base

        logger.info(
            "AgentService: creating LiteLLMModel model_id=%s api_base=%s api_key_prefix=%s...",
            model_id, api_base, api_key[:15] if api_key else "EMPTY",
        )

        # 如果设置了 LITELLM_PROXY_URL，通过它路由
        if litellm_proxy:
            lite_kwargs["api_base"] = litellm_proxy
            proxy_key = os.environ.get("LITELLM_MASTER_KEY", "")
            lite_kwargs["api_key"] = proxy_key if proxy_only else (proxy_key or api_key)
            logger.info("AgentService: routing via LiteLLM proxy: %s", litellm_proxy)

        try:
            agent_model = LiteLLMModel(**lite_kwargs)
            agent = ToolCallingAgent(
                tools=tools,
                model=agent_model,
                instructions=system_prompt,
                max_steps=max_steps,
            )
        except Exception as e:
            reset_tool_context(context_tokens)
            logger.error("AgentService: initialization failed: %s", e, exc_info=True)
            return AgentResult(
                content="", model_used=model, exit_code=2,
                error_message=f"Agent initialization failed: {e}",
            )

        logger.info(
            "AgentService: starting agent model=%s provider=%s max_steps=%d tools=%d",
            model_id, provider, max_steps, len(tools),
        )

        # 6. 在线程中执行（Smolagents 是同步的）
        try:
            result_content = await asyncio.wait_for(
                asyncio.to_thread(agent.run, task.prompt),
                timeout=task.timeout_seconds,
            )
        except TimeoutError:
            duration = time.monotonic() - start
            interrupt = getattr(agent, "interrupt", None)
            if callable(interrupt):
                interrupt()
            logger.error("AgentService: timed out after %.1fs", task.timeout_seconds)
            return AgentResult(
                content="", steps=self._extract_step_count(agent),
                duration_seconds=duration, model_used=model, exit_code=124,
                error_message=f"Agent timed out after {task.timeout_seconds:g} seconds",
            )
        except Exception as e:
            duration = time.monotonic() - start
            logger.error("AgentService: agent.run failed: %s", e, exc_info=True)
            return AgentResult(
                content="",
                steps=self._extract_step_count(agent),
                duration_seconds=duration,
                model_used=model,
                exit_code=1,
                error_message=str(e),
            )
        finally:
            reset_tool_context(context_tokens)

        duration = time.monotonic() - start

        # agent.run() 返回的是字符串
        if isinstance(result_content, str):
            content = result_content
        elif isinstance(result_content, dict):
            content = result_content.get("output", str(result_content))
        else:
            content = str(result_content)

        # 清理 think 标签残留
        content = self._clean_output(content)

        # A transport-level success with an empty model response is not a
        # successful agent run. Never persist it as reusable memory.
        if not content:
            return AgentResult(
                content="",
                steps=self._extract_step_count(agent),
                duration_seconds=duration,
                model_used=model,
                exit_code=1,
                error_message="Agent returned an empty response",
            )

        # 7. 存储记忆
        memory_id = None
        if task.memory_type and content:
            try:
                memory_id = await self.memory.memorize(MemoryRecord(
                    memory_type=task.memory_type,
                    source_id=task.source_id,
                    title=self._extract_title(content),
                    content=content,
                    metadata=task.memory_filters or {},
                ))
                logger.info("AgentService: memory stored id=%d", memory_id)
            except Exception as e:
                logger.warning("AgentService: memory store failed: %s", e)

        logger.info(
            "AgentService: finished duration=%.1fs content_len=%d memory_id=%s",
            duration, len(content), memory_id,
        )

        return AgentResult(
            content=content,
            steps=self._extract_step_count(agent),
            duration_seconds=duration,
            model_used=model,
            exit_code=0,
            memory_id=memory_id,
        )

    async def check_available(self) -> bool:
        """检查 Agent 服务是否可用"""
        # Importing this module already validates the required dependency.
        return True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_task(task: AgentTask) -> str:
        if not isinstance(task.prompt, str) or not task.prompt.strip():
            return "prompt must not be empty"
        if len(task.prompt) > 500_000:
            return "prompt exceeds the 500000 character limit"
        if not isinstance(task.provider_config, dict):
            return "provider_config must be a mapping"
        provider = task.provider_config.get("provider", "openai")
        if not isinstance(provider, str) or not provider.strip():
            return "provider_config.provider must be a non-empty string"
        if not task.provider_config.get("default_model"):
            return "provider_config.default_model is required"
        api_base = task.provider_config.get("api_base_url", "")
        if api_base:
            if not isinstance(api_base, str):
                return "provider_config.api_base_url must be a string"
            parsed = urlparse(api_base)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return "provider_config.api_base_url must be an HTTP(S) URL"
        if not task.provider_config.get("api_key") and not os.environ.get("LITELLM_PROXY_URL"):
            return "provider_config.api_key is required"
        if isinstance(task.max_steps, bool) or not isinstance(task.max_steps, int) or not 1 <= task.max_steps <= 100:
            return "max_steps must be between 1 and 100"
        if (
            isinstance(task.timeout_seconds, bool)
            or not isinstance(task.timeout_seconds, (int, float))
            or not 1 <= task.timeout_seconds <= 7200
        ):
            return "timeout_seconds must be between 1 and 7200"
        if task.memory_filters is not None and not isinstance(task.memory_filters, dict):
            return "memory_filters must be a mapping"
        return ""

    @staticmethod
    def _extract_step_count(agent) -> int:
        """Read the public memory shape used by current smolagents versions."""
        memory = getattr(agent, "memory", None)
        steps = getattr(memory, "steps", None)
        return len(steps) if isinstance(steps, (list, tuple)) else 0

    def _build_system_prompt(
        self,
        skill_scope: str,
        fallback_prompt: str,
        memories: list,
    ) -> str:
        """构建完整的 system prompt = skill 内容 + 历史记忆"""
        parts = []

        # Explicit instructions have priority; otherwise load the scoped skill.
        if fallback_prompt:
            parts.append(fallback_prompt)
        elif skill_scope:
            skill = self.skill_registry.get_skill_by_scope(skill_scope)
            if skill and skill.content:
                parts.append(skill.content)
                logger.info("AgentService: using skill scope=%s", skill_scope)

        # 3. 历史记忆
        if memories:
            memory_text = MemoryManager.format_memories_for_prompt(memories)
            parts.append(memory_text)

        return "\n\n".join(parts) if parts else ""

    def _select_tools(self, task: AgentTask) -> list:
        """根据任务类型选择合适的工具集"""
        if task.memory_type == "failure_analysis":
            return list(FAILURE_ANALYSIS_TOOLS)
        # daily_summary / commit_analysis 通常不需要文件工具
        return list(SUMMARY_TOOLS)

    @staticmethod
    def _clean_output(content: str) -> str:
        """清理输出中的 think 标签残留"""
        import re
        # 移除 <｜end▁of▁thinking｜>... 包围块
        content = re.sub(r"<\s*think\s*>.*?<\s*/\s*think\s*>", "", content,
                         flags=re.DOTALL | re.IGNORECASE)
        # 清理多余空行
        content = re.sub(r"\n{3,}", "\n\n", content)
        content = content.strip()
        if len(content) > 1_000_000:
            content = content[:1_000_000] + "\n\n... (output truncated)"
        return content

    @staticmethod
    def _extract_title(content: str, max_len: int = 200) -> str:
        """从内容中提取一句话标题"""
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        # 跳过 markdown 标题行
        for line in lines:
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                return title[:max_len]
        # 取第一个非空行
        if lines:
            return lines[0][:max_len]
        return ""


# ---------------------------------------------------------------------------
# 便捷函数：与 run_with_fallback 保持接口兼容
# ---------------------------------------------------------------------------


async def run_agent(
    prompt: str,
    provider_config: dict,
    system_prompt: str = "",
    work_dir: str | None = None,
    max_steps: int = 20,
    timeout_seconds: float = 1800,
    memory_type: str = "",
    memory_filters: dict | None = None,
    source_id: int | None = None,
    skill_scope: str = "",
    db=None,
) -> AgentResult:
    """
    便捷函数：执行一次 Agent 任务（接口与 run_with_fallback 类似）。

    注意：需要传入 db session。
    """
    if db is None:
        raise AgentServiceError("db session is required for AgentService")

    agent_svc = AgentService(db)
    return await agent_svc.run(AgentTask(
        prompt=prompt,
        provider_config=provider_config,
        system_prompt=system_prompt,
        skill_scope=skill_scope,
        max_steps=max_steps,
        timeout_seconds=timeout_seconds,
        memory_type=memory_type,
        memory_filters=memory_filters,
        source_id=source_id,
        work_dir=work_dir,
    ))
