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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from smolagents import ToolCallingAgent, LiteLLMModel

from app.services.agent_tools import (
    FAILURE_ANALYSIS_TOOLS,
    SUMMARY_TOOLS,
    set_tool_context,
)
from app.services.memory_manager import MemoryManager, MemoryRecord
from app.services.skill_registry import SkillRegistry, get_skill_registry
from app.models.memory import AnalysisMemory
from app.models.daily_summary import LLMProviderConfig

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
        provider = task.provider_config.get("provider", "unknown").lower()
        model = task.provider_config.get("default_model", "claude-sonnet-4-20250514")
        api_key = task.provider_config.get("api_key", "")
        api_base = task.provider_config.get("api_base_url", "")
        max_steps = task.max_steps or self.DEFAULT_MAX_STEPS

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
        set_tool_context(
            memory_manager=self.memory,
            github_token=os.environ.get("GITHUB_TOKEN", ""),
        )

        # 5. 创建模型和 Agent
        prefix = _detect_prefix(provider, api_base)
        model_id = f"{prefix}/{model}"

        lite_kwargs = {
            "model_id": model_id,
            "api_key": api_key,
        }
        if api_base:
            lite_kwargs["api_base"] = api_base

        # 如果设置了 LITELLM_PROXY_URL，通过它路由
        litellm_proxy = os.environ.get("LITELLM_PROXY_URL", "")
        if litellm_proxy and provider != "anthropic":
            lite_kwargs["api_base"] = litellm_proxy
            logger.info("AgentService: routing via LiteLLM proxy: %s", litellm_proxy)

        agent_model = LiteLLMModel(**lite_kwargs)

        agent = ToolCallingAgent(
            tools=tools,
            model=agent_model,
            instructions=system_prompt,
            max_steps=max_steps,
        )

        logger.info(
            "AgentService: starting agent model=%s provider=%s max_steps=%d tools=%d",
            model_id, provider, max_steps, len(tools),
        )

        # 6. 在线程中执行（Smolagents 是同步的）
        try:
            result_content = await asyncio.to_thread(
                agent.run, task.prompt
            )
        except Exception as e:
            duration = time.monotonic() - start
            logger.error("AgentService: agent.run failed: %s", e, exc_info=True)
            return AgentResult(
                content="",
                steps=0,
                duration_seconds=duration,
                model_used=model,
                exit_code=1,
                error_message=str(e),
            )

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
            steps=0,  # Smolagents current version doesn't expose step count easily
            duration_seconds=duration,
            model_used=model,
            exit_code=0,
            memory_id=memory_id,
        )

    async def check_available(self) -> bool:
        """检查 Agent 服务是否可用"""
        try:
            # 验证 Smolagents 可导入
            from smolagents import ToolCallingAgent, LiteLLMModel  # noqa: F811
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_system_prompt(
        self,
        skill_scope: str,
        fallback_prompt: str,
        memories: list,
    ) -> str:
        """构建完整的 system prompt = skill 内容 + 历史记忆"""
        parts = []

        # 1. Skill 内容
        if skill_scope:
            skill = self.skill_registry.get_skill_by_scope(skill_scope)
            if skill and skill.content:
                parts.append(skill.content)
                logger.info("AgentService: using skill scope=%s", skill_scope)

        # 2. Fallback prompt（如果 skill 没有加载到）
        if not parts and fallback_prompt:
            parts.append(fallback_prompt)

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
        return content.strip()

    @staticmethod
    def _extract_title(content: str, max_len: int = 200) -> str:
        """从内容中提取一句话标题"""
        lines = [l.strip() for l in content.split("\n") if l.strip()]
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
        memory_type=memory_type,
        memory_filters=memory_filters,
        source_id=source_id,
        work_dir=work_dir,
    ))
