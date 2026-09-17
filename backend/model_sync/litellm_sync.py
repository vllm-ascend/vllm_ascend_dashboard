"""
LiteLLM Provider 同步服务

从数据库读取启用的 LLM provider，生成 LiteLLM 配置文件，
写入共享卷后，由 LiteLLM 容器入口监视并重启代理子进程。
"""
import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiohttp

from infrastructure.core.config import settings

logger = logging.getLogger(__name__)


class LiteLLMConfigSyncError(RuntimeError):
    """Raised when a saved provider cannot be routed by the live gateway."""


_RUNTIME_MODEL_POLL_ATTEMPTS = 40
_RUNTIME_MODEL_POLL_INTERVAL_SECONDS = 0.5

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
_CONFIG_FILE = settings.LITELLM_CONFIG_FILE


def _yaml_value(v: str) -> str:
    """安全转义 YAML 值 — 普通值不加引号"""
    # 只有包含特殊字符时才加引号
    if any(c in v for c in ':#{}[]|>!%@"\'\n'):
        return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return v


def _model_to_yaml(model_list: list[dict]) -> str:
    """将 model_list 转为 YAML 片段"""
    lines = ["model_list:"]
    for m in model_list:
        lines.append(f"  - model_name: {_yaml_value(m['model_name'])}")
        lines.append("    litellm_params:")
        for k, v in m["litellm_params"].items():
            lines.append(f"      {k}: {_yaml_value(v)}")
    return "\n".join(lines)


def _build_config_yaml(model_list: list[dict]) -> str:
    """生成完整 LiteLLM 配置"""
    models_yaml = _model_to_yaml(model_list)
    return f"""general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY

{models_yaml}

litellm_settings:
  drop_params: true

router_settings:
  disable_responses_api: true
  num_retries: 1
  request_timeout: 600
"""


class LiteLLMSync:
    """同步数据库 provider 配置到 LiteLLM 网关"""

    def __init__(self, litellm_url: str | None = None):
        self.litellm_url = (litellm_url or settings.LITELLM_PROXY_URL).rstrip("/")
        self.master_key = settings.LITELLM_MASTER_KEY or "sk-litellm-master-key-change-me"

    @property
    def available(self) -> bool:
        return bool(self.litellm_url)

    @staticmethod
    def _write_config(config_path: Path, content: str) -> None:
        """Write atomically where possible and support single-file bind mounts."""
        temporary_path = config_path.with_suffix(
            f"{config_path.suffix}.{uuid4().hex}.tmp"
        )
        try:
            temporary_path.write_text(content, encoding="utf-8")
            temporary_path.replace(config_path)
        except OSError:
            # A Docker single-file bind mount can allow writes to the mounted
            # file while forbidding sibling creation/replacement in /app.
            temporary_path.unlink(missing_ok=True)
            config_path.write_text(content, encoding="utf-8")

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
        """Persist active providers and verify the live LiteLLM routes.

        The production LiteLLM 1.91 image does not implement the former
        ``/config/reload`` endpoint, and its dynamic model endpoint requires
        LiteLLM's own database (which we intentionally do not run).  The
        compose entrypoint watches this bind-mounted file and restarts only
        the proxy process.  Wait for the live model list before success.
        """
        from sqlalchemy import select

        from infrastructure.persistence.models.daily_summary import LLMProviderConfig

        stmt = select(LLMProviderConfig).where(LLMProviderConfig.is_active)
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
                    "api_key": c.decrypted_api_key,
                    "api_base": c.api_base_url or "",
                },
            })

        if not model_list:
            logger.warning("No providers with API keys configured")
            return 0

        content = _build_config_yaml(model_list)

        config_path = Path(_CONFIG_FILE)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        previous_content = config_path.read_text(encoding="utf-8") if config_path.exists() else None
        self._write_config(config_path, content)
        logger.info("LiteLLM config written to %s (%d models)", _CONFIG_FILE, len(model_list))

        try:
            if self.litellm_url:
                await self._wait_for_runtime_models(model_list)
        except Exception:
            # Do not leave a file that will silently take effect on the next
            # proxy restart when the corresponding database update failed.
            if previous_content is None:
                config_path.unlink(missing_ok=True)
            else:
                self._write_config(config_path, previous_content)
            raise

        logger.info("LiteLLM sync: %d providers configured", len(model_list))
        return len(model_list)

    async def _wait_for_runtime_models(self, model_list: list[dict[str, Any]]) -> None:
        """Wait until the file-watching proxy has loaded every requested model."""
        headers = {"Authorization": f"Bearer {self.master_key}"}
        timeout = aiohttp.ClientTimeout(total=10)
        requested_names = {str(item["model_name"]) for item in model_list}
        last_error = ""
        async with aiohttp.ClientSession() as session:
            for attempt in range(_RUNTIME_MODEL_POLL_ATTEMPTS):
                try:
                    available = await self._runtime_model_names(session, headers, timeout)
                    missing = sorted(requested_names - available)
                    if not missing:
                        logger.info("LiteLLM loaded configured model(s): %s", ", ".join(sorted(requested_names)))
                        return
                    last_error = "missing: " + ", ".join(missing)
                except LiteLLMConfigSyncError as exc:
                    # The watcher is deliberately restarting the proxy. A
                    # short connection failure is expected during that swap.
                    last_error = str(exc)
                if attempt + 1 < _RUNTIME_MODEL_POLL_ATTEMPTS:
                    await asyncio.sleep(_RUNTIME_MODEL_POLL_INTERVAL_SECONDS)

        raise LiteLLMConfigSyncError(
            "LiteLLM did not load the updated configuration within "
            f"{_RUNTIME_MODEL_POLL_ATTEMPTS * _RUNTIME_MODEL_POLL_INTERVAL_SECONDS:g}s ({last_error})"
        )

    async def _runtime_model_names(
        self,
        session: aiohttp.ClientSession,
        headers: dict[str, str],
        timeout: aiohttp.ClientTimeout,
    ) -> set[str]:
        try:
            async with session.get(
                f"{self.litellm_url}/v1/models",
                headers=headers,
                timeout=timeout,
            ) as response:
                if response.status != 200:
                    detail = (await response.text()).strip()
                    raise LiteLLMConfigSyncError(
                        f"LiteLLM model-list check failed ({response.status}): {detail[:300]}"
                    )
                payload = await response.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise LiteLLMConfigSyncError(f"LiteLLM model-list check failed: {exc}") from exc

        entries = payload.get("data", []) if isinstance(payload, dict) else []
        return {
            str(entry.get("id") or entry.get("model_name"))
            for entry in entries
            if isinstance(entry, dict) and (entry.get("id") or entry.get("model_name"))
        }

_litellm_sync: LiteLLMSync | None = None


def get_litellm_sync() -> LiteLLMSync:
    global _litellm_sync
    if _litellm_sync is None:
        _litellm_sync = LiteLLMSync()
    return _litellm_sync

