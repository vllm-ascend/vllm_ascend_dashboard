"""
LiteLLM Provider 同步服务

从数据库读取启用的 LLM provider，生成 LiteLLM 配置文件，
写入共享卷后触发热加载。前台页面修改 provider 后重启 backend 即可生效。
"""
import logging
import os
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# provider → LiteLLM model 前缀映射
_PROVIDER_PREFIX = {
    "openai": "openai",
    "qwen": "openai",
    "anthropic": "anthropic",
    "deepseek": "deepseek",
    "zhipu": "openai",
    "glm": "openai",
}


def _detect_prefix(provider: str, api_base: str) -> str:
    """根据 provider 类型和 api_base_url 推测正确的 LiteLLM 前缀

    api_base 优先级更高 —— 比如 provider=openai 但 api_base=api.deepseek.com，
    应该用 deepseek/ 前缀，否则 LiteLLM 走 OpenAI Responses API 会报错。
    """
    base_lower = (api_base or "").lower()
    # 按 api_base 特征匹配
    if "deepseek" in base_lower:
        return "deepseek"
    if "bigmodel" in base_lower or "zhipu" in base_lower:
        return "openai"
    if "dashscope" in base_lower or "aliyuncs" in base_lower:
        return "openai"
    if "openai" in base_lower:
        return "openai"
    if "anthropic" in base_lower:
        return "anthropic"
    # fallback: 按 provider 名匹配
    return _PROVIDER_PREFIX.get(provider, "openai")

# config 写入路径（通过 LITELLM_CONFIG_FILE 环境变量指定）
_CONFIG_FILE = os.environ.get("LITELLM_CONFIG_FILE", "/app/litellm_config.yaml")


def _model_to_yaml(model_list: list[dict]) -> str:
    """将 model_list 转为 YAML 片段"""
    lines = ["model_list:"]
    for m in model_list:
        lines.append(f"  - model_name: {m['model_name']}")
        lines.append("    litellm_params:")
        for k, v in m["litellm_params"].items():
            lines.append(f"      {k}: {v}")
    return "\n".join(lines)


def _build_config_yaml(model_list: list[dict]) -> str:
    """生成完整 LiteLLM 配置"""
    models_yaml = _model_to_yaml(model_list)
    return f"""general_settings:
  master_key: sk-litellm-master-key-change-me

{models_yaml}

litellm_settings:
  drop_params: true

router_settings:
  num_retries: 1
  request_timeout: 600
"""


class LiteLLMSync:
    """同步数据库 provider 配置到 LiteLLM 网关"""

    def __init__(self, litellm_url: Optional[str] = None):
        self.litellm_url = (litellm_url or os.environ.get("LITELLM_PROXY_URL", "")).rstrip("/")
        self.master_key = os.environ.get("LITELLM_MASTER_KEY", "sk-litellm-master-key-change-me")

    @property
    def available(self) -> bool:
        return bool(self.litellm_url)

    async def health_check(self) -> bool:
        if not self.available:
            return False
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{self.litellm_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                    return r.status == 200
        except Exception:
            return False

    async def sync_from_db(self, db_session) -> int:
        """从 DB 读取 provider → 生成 YAML → 写入文件 → 热加载"""
        from sqlalchemy import select
        from app.models.daily_summary import LLMProviderConfig

        stmt = select(LLMProviderConfig).where(LLMProviderConfig.enabled == True)
        result = await db_session.execute(stmt)
        configs = result.scalars().all()

        if not configs:
            logger.warning("No enabled LLM providers found in DB")
            return 0

        model_list = []
        for c in configs:
            if not c.api_key:
                continue
            prefix = _detect_prefix(c.provider, c.api_base_url or "")
            model_list.append({
                "model_name": c.default_model,
                "litellm_params": {
                    "model": f"{prefix}/{c.default_model}",
                    "api_key": c.api_key,
                    "api_base": c.api_base_url or "",
                },
            })

        if not model_list:
            logger.warning("No providers with API keys configured")
            return 0

        content = _build_config_yaml(model_list)

        try:
            Path(_CONFIG_FILE).write_text(content, encoding="utf-8")
            logger.info("LiteLLM config written to %s (%d models)", _CONFIG_FILE, len(model_list))
        except Exception as e:
            logger.error("Failed to write LiteLLM config: %s", e)
            return 0

        if self.litellm_url:
            await self._reload()

        logger.info("LiteLLM sync: %d providers configured", len(model_list))
        return len(model_list)

    async def _reload(self) -> bool:
        """通过 Docker socket 重启 LiteLLM 容器"""
        import aiohttp
        socket_path = "/var/run/docker.sock"
        if not os.path.exists(socket_path):
            logger.warning("Docker socket not available, LiteLLM needs manual restart")
            return False
        try:
            conn = aiohttp.UnixConnector(path=socket_path)
            async with aiohttp.ClientSession(connector=conn) as s:
                async with s.post(
                    "http://localhost/containers/vllm-dashboard-litellm/restart",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as r:
                    ok = r.status in (204, 200)
                    if ok:
                        logger.info("LiteLLM container restarted via Docker API")
                    else:
                        body = await r.text()
                        logger.warning("LiteLLM restart: %d %s", r.status, body[:200])
                    return ok
        except Exception as e:
            logger.warning("LiteLLM restart error: %s", e)
            return False


_litellm_sync: Optional[LiteLLMSync] = None


def get_litellm_sync() -> LiteLLMSync:
    global _litellm_sync
    if _litellm_sync is None:
        _litellm_sync = LiteLLMSync()
    return _litellm_sync
