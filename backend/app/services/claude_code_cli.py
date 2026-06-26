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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Claude Code CLI 日志持久化目录
_CLI_LOG_DIR = Path(__file__).parent.parent.parent / "data" / "claude_logs"

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


def _save_cli_log(
    provider: str, model: str, prompt: str, system_prompt: str,
    stdout: str, stderr: str, duration: float, exit_code: int, route: str,
    tool_calls: list[str] | None = None,
    raw_json: dict | None = None,
) -> str:
    """持久化保存 Claude Code CLI 调用日志"""
    try:
        now = datetime.now(timezone.utc)
        date_dir = _CLI_LOG_DIR / now.strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{now.strftime('%H%M%S')}_{provider}_{model}.log"
        filepath = date_dir / filename

        filepath.write_text(f"""\
{'='*60}
Claude Code CLI Call Log
{'='*60}
Time:      {now.isoformat()}
Provider:  {provider}
Model:     {model}
Route:     {route}
Duration:  {duration:.1f}s
Exit Code: {exit_code}

--- SYSTEM PROMPT ---
{system_prompt or '(none)'}

--- USER PROMPT ---
{prompt}

--- STDOUT ---
{stdout or '(empty)'}

--- STDERR ---
{stderr or '(empty)'}

--- TOOL CALLS ---
{chr(10).join(tool_calls) if tool_calls else '(none)'}

--- RAW JSON (full CLI interaction) ---
{json.dumps(raw_json, indent=2, ensure_ascii=False) if raw_json else '(not available)'}

{'='*60}
""", encoding="utf-8")
        return str(filepath)
    except Exception as e:
        logger.warning("Failed to save CLI log: %s", e)
        return ""


# ---------------------------------------------------------------------------
# ClaudeCodeCLI
# ---------------------------------------------------------------------------

class ClaudeCodeCLI:
    """Claude Code CLI 封装 — 替代 LLMClient.generate()"""

    # 可配置的默认值
    DEFAULT_MAX_TURNS: int = 10
    DEFAULT_TIMEOUT_SECONDS: int = 1800
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
        # 生成 debug 日志路径（轮次级交互记录）
        now = datetime.now(timezone.utc)
        debug_dir = _CLI_LOG_DIR / now.strftime("%Y-%m-%d")
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_file = debug_dir / f"{now.strftime('%H%M%S')}_{provider}_{model}_debug.log"
        args = self._build_args(prompt, system_prompt, turns, output_format, str(debug_file))

        proxy: "FormatProxy | None" = None
        litellm_url = os.environ.get("LITELLM_PROXY_URL", "")

        # ── 路由决策 ──
        if litellm_url and provider != "anthropic":
            # FormatProxy (Anthropic→OpenAI) → LiteLLM → upstream
            from app.services.format_proxy import FormatProxy

            proxy = FormatProxy(
                upstream_base_url=litellm_url,
                upstream_api_key="sk-litellm-master-key-change-me",
                upstream_model=model,
            )
            await proxy.start()
            proxy.set_log_file(str(debug_file).replace("_debug.log", "_conversation.json"))

            env = self._build_env_direct(
                api_key="PROXY_MANAGED",
                api_base=proxy.listen_url,
                model=model,
            )
            logger.info(
                "ClaudeCodeCLI (FormatProxy→LiteLLM): %s provider=%s model=%s",
                litellm_url, provider, model,
            )
        elif provider == "anthropic":
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
            proxy.set_log_file(str(debug_file).replace("_debug.log", "_conversation.json"))

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
        # root 用户不允许 --dangerously-skip-permissions，通过 su 切到 appuser
        if os.geteuid() == 0:
            cmd_str = " ".join(
                [shlex.quote(cli_path)] + [shlex.quote(a) for a in args]
            )
            # su -m: preserve environment + 显式设置 HOME，避免 CLI 找 /.agents/skills
            cmd = ["su", "-m", "appuser", "-c", f"export HOME=/home/appuser; {cmd_str}"]
        else:
            cmd = [cli_path] + args

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=work_dir or os.getcwd(),
            )

            try:
                prompt_bytes = (getattr(self, "_stdin_prompt", prompt)).encode("utf-8")
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=prompt_bytes),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise ClaudeCLITimeout(
                    f"Claude Code CLI timed out after {self._timeout}s"
                )

            duration = time.monotonic() - start
            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

            result = None
            if proc.returncode != 0:
                # CLI 失败，但仍然保存日志并尝试解析已产出的内容
                route_name = "litellm" if litellm_url else ("direct" if provider == "anthropic" else "formatproxy")
                # 尝试从 stdout 提取内容（如 hit max_turns 但已写了报告）
                partial_result = None
                try:
                    partial_result = self._parse_output(
                        stdout, stderr, duration, output_format, model, proc.returncode,
                    )
                except Exception:
                    pass
                _save_cli_log(
                    provider=provider, model=model,
                    prompt=prompt, system_prompt=system_prompt,
                    stdout=stdout, stderr=stderr,
                    duration=duration, exit_code=proc.returncode,
                    route=route_name,
                    tool_calls=partial_result.tool_calls if partial_result and partial_result.tool_calls else None,
                    raw_json=partial_result.raw_json if partial_result else None,
                )
                # 如果能解析出非空内容，返回部分结果而不是抛异常
                if partial_result and partial_result.content and len(partial_result.content.strip()) > 100:
                    logger.warning(
                        "CLI exited with code %d but produced partial output (%d chars), using it",
                        proc.returncode, len(partial_result.content),
                    )
                    return partial_result
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

            # 持久化日志
            route_name = "litellm" if litellm_url else ("direct" if provider == "anthropic" else "formatproxy")
            _save_cli_log(
                provider=provider, model=model,
                prompt=prompt, system_prompt=system_prompt,
                stdout=stdout, stderr=stderr,
                duration=duration, exit_code=proc.returncode,
                route=route_name,
                tool_calls=result.tool_calls if result.tool_calls else None,
                raw_json=result.raw_json,
            )

            return result

        finally:
            # 清理临时文件
            for attr in ("_sys_prompt_file",):
                path = getattr(self, attr, None)
                if path:
                    try:
                        import os as _os
                        _os.unlink(path)
                    except Exception:
                        pass
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

        # 传递 GITHUB_TOKEN，CLI 可以用 curl 拉 CI 日志
        from app.core.config import settings
        if settings.GITHUB_TOKEN:
            env["GITHUB_TOKEN"] = settings.GITHUB_TOKEN

        # 确保 HOME 正确设置，CLI 会用它找配置目录
        if "HOME" not in env or not env["HOME"]:
            env["HOME"] = "/home/appuser"

        return env

    def _build_args(
        self,
        prompt: str,
        system_prompt: str,
        max_turns: int,
        output_format: str,
        debug_file: str = "",
    ) -> list[str]:
        """构建 claude CLI 命令行参数（prompt 较大时通过 stdin 传入）"""
        import tempfile
        from pathlib import Path

        self._stdin_prompt = prompt  # 通过 stdin 传入
        args = ["--print", "--max-turns", str(max_turns)]

        if debug_file:
            args.extend(["--debug", "--debug-file", debug_file])

        if output_format == "json":
            args.extend(["--output-format", "json"])

        if system_prompt:
            # 写到 appuser 可读的目录（/tmp 对 su 用户不可见）
            sp_dir = Path("/home/appuser/.claude/tmp")
            sp_dir.mkdir(parents=True, exist_ok=True)
            sys_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8", dir=str(sp_dir)
            )
            sys_file.write(system_prompt)
            sys_file.close()
            import shutil
            shutil.chown(sys_file.name, user="appuser")
            args.extend(["--system-prompt-file", sys_file.name])
            self._sys_prompt_file = sys_file.name

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


async def run_with_fallback(
    prompt: str,
    provider_config: dict,
    system_prompt: str = "",
    work_dir: str | None = None,
    max_turns: int = 10,
    timeout_seconds: int = 1800,
    output_format: str = "text",
) -> ClaudeCodeResult:
    """
    通过 Claude Code CLI 执行分析（仅 CLI，无降级）。
    """
    cli = ClaudeCodeCLI(timeout_seconds=timeout_seconds)

    try:
        return await cli.run(
            prompt=prompt,
            provider_config=provider_config,
            work_dir=work_dir,
            max_turns=max_turns,
            system_prompt=system_prompt,
            output_format=output_format,
        )
    except (ClaudeCLINotAvailable, ClaudeCLITimeout) as e:
        raise  # 直接抛出，由上层标记分析失败，不降级到 direct API
