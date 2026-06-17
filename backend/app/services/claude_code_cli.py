"""
Claude Code CLI 调用封装层

将原有的 LLMClient.generate() (直接 API SDK 调用) 替换为
subprocess 调用 claude CLI，以利用其多步推理、工具调用、
文件读取等能力。

ccswitch 多 provider 支持：
  - anthropic provider → 直接设置 ANTHROPIC_BASE_URL/API_KEY 环境变量
  - 其他 provider → 启动本地 FormatProxy，翻译 Anthropic ↔ OpenAI 格式，
    实现与 cc-switch (github.com/farion1231/cc-switch) 同等的代理翻译能力
"""
import asyncio
import json
import logging
import os
import shlex
import shutil
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ClaudeCodeResult:
    """Claude Code CLI 调用结果"""
    content: str
    turns: int = 0
    duration_seconds: float = 0.0
    model_used: str = ""
    tool_calls: list[str] = field(default_factory=list)
    raw_json: dict | None = None
    exit_code: int = 0
    stderr: str = ""


class ClaudeCLINotAvailable(Exception):
    """Claude Code CLI 不可用异常（触发降级）"""
    pass


class ClaudeCLITimeout(Exception):
    """Claude Code CLI 执行超时"""
    pass


# ---------------------------------------------------------------------------
# ClaudeCodeCLI
# ---------------------------------------------------------------------------

class ClaudeCodeCLI:
    """Claude Code CLI 封装 — 替代 LLMClient.generate()"""

    # 可配置的默认值
    DEFAULT_MAX_TURNS: int = 10
    DEFAULT_TIMEOUT_SECONDS: int = 600
    DEFAULT_MODEL: str = "claude-sonnet-4-20250514"

    def __init__(
        self,
        cli_path: str | None = None,
        max_turns: int | None = None,
        timeout_seconds: int | None = None,
    ):
        """
        Args:
            cli_path: claude CLI 路径（None 则自动探测）
            max_turns: 默认最大推理轮数
            timeout_seconds: 默认超时（秒）
        """
        self._cli_path = cli_path
        self._max_turns = max_turns or self.DEFAULT_MAX_TURNS
        self._timeout = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        prompt: str,
        provider_config: dict,
        work_dir: str | None = None,
        max_turns: int | None = None,
        system_prompt: str = "",
        output_format: str = "text",
    ) -> ClaudeCodeResult:
        """
        执行一次 Claude Code CLI 调用。

        路由策略（按优先级）：
        1. CLAUDE_PROXY_URL 环境变量 → LiteLLM 网关（生产环境）
        2. provider == "anthropic" → 直连 Anthropic API
        3. 其他 → FormatProxy 本地代理（开发环境 fallback）

        Args:
            prompt: 用户提示词
            provider_config: {provider, api_key, api_base_url, default_model}
            work_dir: 工作目录
            max_turns: 最大推理轮数
            system_prompt: 系统提示词
            output_format: 输出格式
        """
        cli_path = self._resolve_cli_path()
        provider = provider_config.get("provider", "unknown").lower()
        model = provider_config.get("default_model", self.DEFAULT_MODEL)
        api_key = provider_config.get("api_key", "")
        api_base = provider_config.get("api_base_url", "")

        turns = max_turns or self._max_turns
        args = self._build_args(prompt, system_prompt, turns, output_format)

        proxy: "FormatProxy | None" = None
        litellm_url = os.environ.get("LITELLM_PROXY_URL", "")

        # ── 路由决策 ──
        if litellm_url and provider != "anthropic":
            # 生产环境：非 Anthropic → LiteLLM 网关
            env = self._build_env_direct(
                api_key="sk-litellm-master-key-change-me",
                api_base=litellm_url,
                model=model,
            )
            logger.info(
                "ClaudeCodeCLI (via LiteLLM): %s provider=%s model=%s",
                litellm_url, provider, model,
            )
        elif provider == "anthropic":
            # 开发环境：直连 Anthropic
            env = self._build_env_direct(api_key, api_base, model)
            logger.info(
                "ClaudeCodeCLI (direct): provider=%s model=%s max_turns=%d",
                provider, model, turns,
            )
        else:
            # 开发环境：FormatProxy 本地代理（Anthropic ↔ OpenAI 翻译）
            from app.services.format_proxy import FormatProxy

            proxy = FormatProxy(
                upstream_base_url=api_base or "https://api.openai.com/v1",
                upstream_api_key=api_key,
                upstream_model=model,
            )
            await proxy.start()

            env = self._build_env_direct(
                api_key="PROXY_MANAGED",
                api_base=proxy.listen_url,
                model=model,
            )
            logger.info(
                "ClaudeCodeCLI (via FormatProxy :%d): provider=%s → model=%s",
                proxy.port, provider, model,
            )

        # ── 执行 CLI ──
        # root 用户不允许 --dangerously-skip-permissions，通过 su -m 切到 appuser
        if os.geteuid() == 0:
            cmd_str = " ".join(
                [shlex.quote(cli_path)] + [shlex.quote(a) for a in args]
            )
            # su -m: preserve environment（保留 ANTHROPIC_* 等环境变量）
            cmd = ["su", "-m", "appuser", "-c", cmd_str]
        else:
            cmd = [cli_path] + args

        start = time.monotonic()
        try:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                    cwd=work_dir or os.getcwd(),
                )

                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                raise ClaudeCLITimeout(
                    f"Claude Code CLI timed out after {self._timeout}s"
                )

            duration = time.monotonic() - start
            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                logger.error(
                    "Claude Code CLI exited with code %d\nstderr: %s",
                    proc.returncode, stderr[:500],
                )
                raise ClaudeCLINotAvailable(
                    f"Claude CLI exited with code {proc.returncode}: {stderr[:200]}"
                )

            result = self._parse_output(
                stdout, stderr, duration, output_format, model, proc.returncode,
            )

            logger.info(
                "ClaudeCodeCLI finished: duration=%.1fs turns=%d content_len=%d",
                duration, result.turns, len(result.content),
            )
            return result

        finally:
            if proxy:
                await proxy.stop()

    async def check_available(self) -> bool:
        """检查 Claude Code CLI 是否可用"""
        try:
            cli_path = self._resolve_cli_path()
            proc = await asyncio.create_subprocess_exec(
                cli_path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return proc.returncode == 0
        except Exception:
            return False

    async def ensure_initialized(self, provider_config: dict) -> bool:
        """
        确保 Claude Code CLI 已初始化（首次使用时可能被 login 阻塞）。

        用最小 prompt 做一次热启动，验证 API key 有效且 CLI 可以正常响应。
        """
        try:
            result = await self.run(
                prompt="reply 'ok'",
                provider_config=provider_config,
                max_turns=1,
                output_format="text",
            )
            return result.exit_code == 0 and len(result.content) > 0
        except Exception as e:
            logger.warning("Claude Code CLI initialization check failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_cli_path(self) -> str:
        """解析 claude CLI 可执行文件路径"""
        if self._cli_path:
            if os.path.isfile(self._cli_path):
                return self._cli_path
            raise ClaudeCLINotAvailable(
                f"Specified claude CLI not found: {self._cli_path}"
            )

        # auto-detect
        resolved = shutil.which("claude")
        if resolved:
            return resolved

        # 尝试常见的全局 npm 安装路径
        candidates = [
            "/usr/local/bin/claude",
            "/usr/bin/claude",
            os.path.expanduser("~/.npm-global/bin/claude"),
            os.path.expanduser("~/node_modules/.bin/claude"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c

        raise ClaudeCLINotAvailable(
            "Claude Code CLI ('claude') not found in PATH. "
            "Install with: npm install -g @anthropic-ai/claude-code"
        )

    def _build_env_direct(self, api_key: str, api_base: str, model: str) -> dict:
        """
        构建 Claude Code CLI 的环境变量。

        等效于 cc-switch 的设置：
        - ANTHROPIC_BASE_URL → CLI 的 API 请求目标
        - ANTHROPIC_API_KEY → 鉴权 token
        - ANTHROPIC_DEFAULT_*_MODEL → 模型别名映射

        当 api_base 指向 FormatProxy 时，即为代理模式（非 Anthropic provider）；
        当 api_base 指向官方 API 时，即为直连模式。
        """
        env = os.environ.copy()

        if api_key:
            env["ANTHROPIC_API_KEY"] = api_key
        if api_base:
            env["ANTHROPIC_BASE_URL"] = api_base

        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = model
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = model
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = model

        env["CLAUDE_CODE_TELEMETRY_DISABLED"] = "1"
        env["CLAUDE_CODE_NO_INTERACTIVE"] = "1"
        env["CLAUDE_CODE_HEADLESS"] = "1"

        return env

    def _build_args(
        self,
        prompt: str,
        system_prompt: str,
        max_turns: int,
        output_format: str,
    ) -> list[str]:
        """构建 claude CLI 命令行参数"""
        args = [
            "-p", prompt,          # 非交互式 prompt
            "--print",             # 将结果打印到 stdout（而非启动交互 REPL）
            "--max-turns", str(max_turns),
        ]

        if output_format == "json":
            args.extend(["--output-format", "json"])

        if system_prompt:
            args.extend(["--system-prompt", system_prompt])

        # 跳过权限确认（仅非 root 用户可用）
        args.append("--dangerously-skip-permissions")

        return args

    def _parse_output(
        self,
        stdout: str,
        stderr: str,
        duration: float,
        output_format: str,
        model: str,
        exit_code: int,
    ) -> ClaudeCodeResult:
        """解析 CLI 输出"""
        content = stdout
        turns = 0
        tool_calls: list[str] = []
        raw_json = None

        if output_format == "json":
            try:
                raw_json = json.loads(stdout)
                # 尝试提取常见字段
                if isinstance(raw_json, dict):
                    content = raw_json.get("result", raw_json.get("content", stdout))
                    turns = raw_json.get("turns", 0)
                    if "tool_calls" in raw_json:
                        tool_calls = raw_json["tool_calls"]
            except json.JSONDecodeError:
                logger.warning("Failed to parse CLI JSON output, using raw stdout")

        return ClaudeCodeResult(
            content=content,
            turns=turns,
            duration_seconds=duration,
            model_used=model,
            tool_calls=tool_calls,
            raw_json=raw_json,
            exit_code=exit_code,
            stderr=stderr,
        )


# ---------------------------------------------------------------------------
# Fallback: 当 CLI 不可用时降级到原有直接 API 调用
# ---------------------------------------------------------------------------

async def fallback_to_direct_api(
    provider_config: dict,
    system_prompt: str,
    user_prompt: str,
) -> ClaudeCodeResult:
    """
    降级策略：CLI 不可用时回退到原有的 LLMClient.generate() 直接 API 调用。
    保持功能不中断。
    """
    from app.services.llm_client import LLMClient

    client = LLMClient()
    try:
        result = await client.generate(
            provider=provider_config.get("provider", "anthropic"),
            model=provider_config.get("default_model", "claude-sonnet-4-20250514"),
            api_key=provider_config.get("api_key", ""),
            api_base=provider_config.get("api_base_url", ""),
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        return ClaudeCodeResult(
            content=result.content,
            duration_seconds=result.generation_time,
            model_used=provider_config.get("default_model", ""),
        )
    except Exception as e:
        raise ClaudeCLINotAvailable(
            f"Both CLI and direct API fallback failed: {e}"
        ) from e


async def run_with_fallback(
    prompt: str,
    provider_config: dict,
    system_prompt: str = "",
    work_dir: str | None = None,
    max_turns: int = 10,
) -> ClaudeCodeResult:
    """
    尝试 Claude Code CLI，不可用时自动降级到直接 API 调用。

    这是推荐的统一入口。

    ccswitch 机制：通过环境变量 ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY
    将 Claude Code CLI 指向任意 Anthropic Messages API 兼容端点。
    目前 DeepSeek、Qwen、SiliconFlow 等主流厂商均已支持该格式。
    """
    cli = ClaudeCodeCLI()

    try:
        return await cli.run(
            prompt=prompt,
            provider_config=provider_config,
            work_dir=work_dir,
            max_turns=max_turns,
            system_prompt=system_prompt,
        )
    except (ClaudeCLINotAvailable, ClaudeCLITimeout) as e:
        logger.warning(
            "Claude Code CLI unavailable, falling back to direct API: %s", e
        )
        return await fallback_to_direct_api(
            provider_config=provider_config,
            system_prompt=system_prompt,
            user_prompt=prompt,
        )
