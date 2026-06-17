"""
LiteLLM Provider 同步服务

在 backend 启动时将数据库中启用的 LLM provider 注册到 LiteLLM 网关，
保证 Claude Code CLI 的请求能正确路由到用户配置的 provider。
"""
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class LiteLLMSync:
    """同步数据库 provider 配置到 LiteLLM 网关"""

    def __init__(self, litellm_url: Optional[str] = None):
        self.litellm_url = (litellm_url or os.environ.get("LITELLM_PROXY_URL", "")).rstrip("/")
        self.master_key = os.environ.get("LITELLM_MASTER_KEY", "sk-litellm-master-key-change-me")

    @property
    def available(self) -> bool:
        return bool(self.litellm_url)

    async def health_check(self) -> bool:
        """检查 LiteLLM 是否可用"""
        if not self.available:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.litellm_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def register_provider(self, provider: str, api_key: str, api_base: str, model: str) -> bool:
        """
        注册一个 provider 到 LiteLLM。

        将 openai / qwen 等 provider 映射为 LiteLLM 的 model 配置。
        这样 Claude Code CLI 请求 model=xxx 时 LiteLLM 知道转发到哪个上游。
        """
        if not self.available:
            return False

        # 将我们的 provider 映射为 LiteLLM 的 model 名
        litellm_model = f"openai/{model}"
        if api_base and "openai.com" not in api_base and "anthropic.com" not in api_base:
            # 对于第三方端点，使用 openai/ 前缀 + 自定义 api_base
            pass

        payload = {
            "model_name": model,
            "litellm_params": {
                "model": litellm_model,
                "api_key": api_key,
            },
        }
        if api_base:
            payload["litellm_params"]["api_base"] = api_base

        try:
            headers = {
                "Authorization": f"Bearer {self.master_key}",
                "Content-Type": "application/json",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.litellm_url}/model/new",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status in (200, 201):
                        logger.info("Registered model '%s' with LiteLLM → %s", model, litellm_model)
                        return True
                    else:
                        body = await resp.text()
                        logger.warning("Failed to register model '%s' with LiteLLM: %d %s", model, resp.status, body[:200])
                        return False
        except Exception as e:
            logger.warning("LiteLLM sync error for model '%s': %s", model, e)
            return False

    async def sync_from_db(self, db_session) -> int:
        """
        从数据库同步所有启用的 provider 到 LiteLLM。

        Returns:
            成功注册的 provider 数量
        """
        from sqlalchemy import select

        from app.models.daily_summary import LLMProviderConfig

        stmt = select(LLMProviderConfig).where(LLMProviderConfig.enabled == True)
        result = await db_session.execute(stmt)
        configs = result.scalars().all()

        count = 0
        for config in configs:
            if not config.api_key:
                continue
            ok = await self.register_provider(
                provider=config.provider,
                api_key=config.api_key,
                api_base=config.api_base_url or "",
                model=config.default_model,
            )
            if ok:
                count += 1

        logger.info("LiteLLM sync: %d/%d providers registered", count, len(configs))
        return count


# 全局单例
_litellm_sync: Optional[LiteLLMSync] = None


def get_litellm_sync() -> LiteLLMSync:
    global _litellm_sync
    if _litellm_sync is None:
        _litellm_sync = LiteLLMSync()
    return _litellm_sync
