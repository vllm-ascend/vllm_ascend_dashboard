"""
Anthropic Messages API ↔ OpenAI Chat Completions API 格式翻译代理

实现 cc-switch 的核心功能：本地 HTTP 代理 + 请求/响应格式翻译，
使 Claude Code CLI 可以使用任意 OpenAI 兼容的 API provider。

架构:
  Claude Code CLI → localhost:{port} → FormatProxy → 上游 API provider
                      (Anthropic 格式)        (OpenAI 格式)
"""
import asyncio
import json
import logging
import time
from typing import Optional

import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)


class FormatProxy:
    """
    本地 HTTP 代理：接收 Anthropic Messages API 请求，
    翻译为 OpenAI Chat Completions 格式，转发到上游 provider，
    再将 OpenAI 响应翻译回 Anthropic 格式返回给 Claude Code CLI。
    """

    def __init__(
        self,
        upstream_base_url: str,
        upstream_api_key: str,
        upstream_model: str,
    ):
        self.upstream_base_url = upstream_base_url.rstrip("/")
        self.upstream_api_key = upstream_api_key
        self.upstream_model = upstream_model

        self._port: int = 0
        self._runner: web.AppRunner | None = None
        self._session: aiohttp.ClientSession | None = None

        # 对话轮次日志
        self._turn_counter: int = 0
        self._conversation_log: list[dict] = []
        self._log_file_path: str | None = None

    def set_log_file(self, path: str) -> None:
        """设置对话日志文件路径"""
        self._log_file_path = path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @property
    def port(self) -> int:
        return self._port

    @property
    def listen_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    async def start(self) -> int:
        """启动代理服务器，返回监听端口"""
        self._session = aiohttp.ClientSession()

        app = web.Application()
        # Anthropic Messages API → 转发
        app.router.add_post("/v1/messages", self._handle_messages)
        # Anthropic token count（模拟）
        app.router.add_post("/v1/messages/count_tokens", self._handle_count_tokens)
        # 健康检查
        app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()

        # 获取实际绑定的端口
        for sock in site._server.sockets:
            self._port = sock.getsockname()[1]
            break

        logger.info(
            "FormatProxy started on %s → %s (model=%s)",
            self.listen_url, self.upstream_base_url, self.upstream_model,
        )
        return self._port

    async def stop(self) -> None:
        """停止代理服务器"""
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
        if self._session:
            await self._session.close()
            self._session = None

        # 保存对话轮次日志
        if self._log_file_path and self._conversation_log:
            try:
                from pathlib import Path
                log_path = Path(self._log_file_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(json.dumps({
                    "total_turns": len(self._conversation_log),
                    "model": self.upstream_model,
                    "conversation": self._conversation_log,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.info("Conversation log saved: %s (%d turns)", log_path, len(self._conversation_log))
            except Exception as e:
                logger.warning("Failed to save conversation log: %s", e)

        logger.info("FormatProxy stopped")

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_count_tokens(self, request: web.Request) -> web.Response:
        """模拟 token count（非关键路径，返回估算值）"""
        try:
            body = await request.json()
        except Exception:
            body = {}
        # 粗略估算
        text = json.dumps(body.get("messages", []))
        count = len(text) // 3
        return web.json_response({"input_tokens": max(count, 1)})

    async def _handle_messages(self, request: web.Request) -> web.StreamResponse:
        """处理 Anthropic POST /v1/messages → 翻译为 OpenAI 格式并转发"""
        try:
            anthropic_body = await request.json()
        except Exception as e:
            return web.json_response(
                {"type": "error", "error": {"type": "invalid_request", "message": str(e)}},
                status=400,
            )

        try:
            openai_body = self._anthropic_to_openai(anthropic_body)
        except Exception as e:
            logger.error("Failed to translate request: %s", e)
            return web.json_response(
                {"type": "error", "error": {"type": "invalid_request", "message": str(e)}},
                status=400,
            )

        # 强制非流式（openai_body 里已设 stream=False），直接用非流式转发
        if openai_body.get("stream"):
            return await self._forward_stream(openai_body, request)
        else:
            return await self._forward_non_stream(openai_body)

    # ------------------------------------------------------------------
    # Request forwarding
    # ------------------------------------------------------------------

    async def _forward_non_stream(self, openai_body: dict) -> web.Response:
        """非流式转发"""
        url = self._chat_completions_url()
        headers = self._upstream_headers()
        self._turn_counter += 1
        turn = self._turn_counter
        t0 = time.monotonic()

        try:
            async with self._session.post(url, json=openai_body, headers=headers) as resp:
                openai_resp = await resp.json()
                elapsed = time.monotonic() - t0
                if resp.status != 200:
                    return web.json_response(
                        self._openai_error_to_anthropic(openai_resp, resp.status),
                        status=resp.status,
                    )
                anthropic_resp = self._openai_resp_to_anthropic(openai_resp, openai_body)

                # 记录对话轮次（含 tool_calls）
                messages_log = []
                for m in openai_body.get("messages", []):
                    entry = {"role": m.get("role", ""), "content": str(m.get("content", ""))[:3000]}
                    # assistant 的 tool_calls
                    if m.get("tool_calls"):
                        entry["tool_calls"] = [
                            {"name": tc.get("function", {}).get("name", ""),
                             "args": str(tc.get("function", {}).get("arguments", ""))[:500]}
                            for tc in m["tool_calls"]
                        ]
                    messages_log.append(entry)

                self._conversation_log.append({
                    "turn": turn,
                    "request": {
                        "model": openai_body.get("model", ""),
                        "messages": messages_log,
                    },
                    "response": {
                        "choices": [
                            {
                                "finish_reason": c.get("finish_reason", ""),
                                "content": str(c.get("message", {}).get("content", ""))[:3000],
                            }
                            for c in openai_resp.get("choices", [])
                        ],
                        "usage": openai_resp.get("usage", {}),
                    },
                    "elapsed_ms": int(elapsed * 1000),
                })

                return web.json_response(anthropic_resp)
        except Exception as e:
            logger.error("Non-stream forward failed: %s", e)
            return web.json_response(
                {"type": "error", "error": {"type": "api_error", "message": str(e)}},
                status=502,
            )

    async def _forward_stream(self, openai_body: dict, request: web.Request) -> web.StreamResponse:
        """流式转发 + SSE 格式翻译"""
        url = self._chat_completions_url()
        headers = self._upstream_headers()

        # 准备 stream response (Anthropic SSE 格式)
        resp = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Transfer-Encoding": "chunked",
            },
        )
        await resp.prepare(request)

        stream_state = {
            "msg_id": f"msg_{int(time.time() * 1000)}",
            "model": self.upstream_model,
            "content_index": 0,
            "tool_use_index": 0,
            "started": False,
            "finished": False,
            "input_tokens": 0,
            "output_tokens": 0,
            "current_tool_call": None,  # (index, id, name)
            "pending_tool_calls": {},  # index → {id, name, arguments}
            "sent_text_block_start": False,
            "sent_tool_blocks": set(),  # indices that have had content_block_start sent
        }

        try:
            async with self._session.post(url, json=openai_body, headers=headers) as upstream:
                if upstream.status != 200:
                    error_text = await upstream.text()
                    logger.error("Upstream stream error %d: %s", upstream.status, error_text[:500])
                    error_sse = self._build_anthropic_sse("error", {
                        "type": "error",
                        "error": {"type": "api_error", "message": f"Upstream {upstream.status}"},
                    })
                    await resp.write(error_sse.encode())
                    await resp.write_eof()
                    return resp

                async for line in upstream.content:
                    line_str = line.decode("utf-8", errors="replace").strip()
                    if not line_str or line_str.startswith(":"):
                        continue
                    if line_str == "data: [DONE]":
                        # 发送结束事件
                        for sse in self._build_stream_end_events(stream_state):
                            await resp.write(sse.encode())
                        stream_state["finished"] = True
                        continue
                    if not line_str.startswith("data: "):
                        continue

                    json_str = line_str[6:]  # strip "data: "
                    try:
                        chunk = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue

                    # 翻译每个 SSE chunk
                    sse_events = self._openai_chunk_to_anthropic_events(chunk, stream_state)
                    for sse in sse_events:
                        await resp.write(sse.encode())

        except Exception as e:
            logger.error("Stream forward failed: %s", e)
            error_sse = self._build_anthropic_sse("error", {
                "type": "error",
                "error": {"type": "api_error", "message": str(e)},
            })
            await resp.write(error_sse.encode())

        await resp.write_eof()
        return resp

    # ------------------------------------------------------------------
    # Format translation: Anthropic → OpenAI (Request)
    # ------------------------------------------------------------------

    def _anthropic_to_openai(self, body: dict) -> dict:
        """将 Anthropic Messages 请求翻译为 OpenAI Chat Completions 请求"""
        openai_messages: list[dict] = []

        # 系统提示词：Anthropic 顶层 system → OpenAI 的首条 system 消息
        system = body.get("system")
        if system:
            if isinstance(system, str):
                openai_messages.append({"role": "system", "content": system})
            elif isinstance(system, list):
                # Anthropic 支持 system 为 content blocks 数组
                text_parts = []
                for block in system:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                if text_parts:
                    openai_messages.append({"role": "system", "content": "\n".join(text_parts)})

        # 消息转换
        for msg in body.get("messages", []):
            role = msg.get("role", "user")
            content = msg.get("content")

            if role in ("user", "assistant"):
                if isinstance(content, str):
                    openai_messages.append({"role": role, "content": content})
                elif isinstance(content, list):
                    # Anthropic content blocks
                    text_parts = []
                    tool_calls_in_msg = []
                    for block in content:
                        block_type = block.get("type")
                        if block_type == "text":
                            text_parts.append(block.get("text", ""))
                        elif block_type == "tool_use":
                            # Anthropic tool_use → OpenAI assistant with tool_calls
                            tool_calls_in_msg.append({
                                "id": block.get("id", ""),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input", {})),
                                },
                            })
                        elif block_type == "tool_result":
                            # Anthropic tool_result → OpenAI tool message
                            tc = block.get("content", "")
                            if isinstance(tc, list):
                                tc = " ".join(
                                    b.get("text", "") for b in tc if isinstance(b, dict) and b.get("type") == "text"
                                )
                            openai_messages.append({
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id", ""),
                                "content": str(tc),
                            })

                    if text_parts:
                        openai_messages.append({"role": role, "content": "\n".join(text_parts)})
                    if tool_calls_in_msg:
                        openai_messages.append({"role": "assistant", "tool_calls": tool_calls_in_msg})
            else:
                # fallback
                openai_messages.append({"role": "user", "content": str(content)})

        # 构建 OpenAI 请求
        openai_body: dict = {
            "model": self.upstream_model,
            "messages": openai_messages,
            "stream": False,  # 强制非流式，避免 SSE 翻译 bug
        }

        if body.get("max_tokens"):
            openai_body["max_tokens"] = body["max_tokens"]
        if body.get("temperature") is not None:
            openai_body["temperature"] = body["temperature"]
        if body.get("top_p") is not None:
            openai_body["top_p"] = body["top_p"]
        if body.get("stop_sequences"):
            openai_body["stop"] = body["stop_sequences"]

        # 工具转换：Anthropic tools → OpenAI tools
        tools = body.get("tools", [])
        if tools:
            openai_tools = []
            for tool in tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                    },
                })
            openai_body["tools"] = openai_tools

        return openai_body

    # ------------------------------------------------------------------
    # Format translation: OpenAI → Anthropic (Response)
    # ------------------------------------------------------------------

    def _openai_resp_to_anthropic(self, openai_resp: dict, openai_body: dict) -> dict:
        """非流式 OpenAI 响应 → Anthropic 响应"""
        choice = openai_resp.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage = openai_resp.get("usage", {})

        content_blocks = []

        # 文本内容
        text_content = message.get("content")
        if text_content:
            content_blocks.append({"type": "text", "text": text_content})

        # 工具调用
        tool_calls = message.get("tool_calls", [])
        for tc in tool_calls:
            func = tc.get("function", {})
            try:
                inp = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                inp = {}
            content_blocks.append({
                "type": "tool_use",
                "id": tc.get("id", ""),
                "name": func.get("name", ""),
                "input": inp,
            })

        # 尝试从最后一个 user message 估算 input_tokens
        input_tokens = usage.get("prompt_tokens", 0)
        if not input_tokens:
            total_text = json.dumps(openai_body.get("messages", []))
            input_tokens = len(total_text) // 3

        return {
            "id": openai_resp.get("id", f"msg_{int(time.time() * 1000)}"),
            "type": "message",
            "role": "assistant",
            "model": self.upstream_model,
            "content": content_blocks,
            "stop_reason": choice.get("finish_reason", "end_turn"),
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": usage.get("completion_tokens", 0),
            },
        }

    def _openai_error_to_anthropic(self, openai_resp: dict, status: int) -> dict:
        """OpenAI 错误响应 → Anthropic 错误响应"""
        error = openai_resp.get("error", {})
        return {
            "type": "error",
            "error": {
                "type": "api_error" if status >= 500 else "invalid_request",
                "message": error.get("message", str(openai_resp)),
            },
        }

    # ------------------------------------------------------------------
    # Streaming SSE translation
    # ------------------------------------------------------------------

    def _openai_chunk_to_anthropic_events(
        self, chunk: dict, state: dict
    ) -> list[str]:
        """将一个 OpenAI SSE chunk 翻译为一组 Anthropic SSE 事件"""
        events: list[str] = []
        choice = chunk.get("choices", [{}])[0]
        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")
        usage = chunk.get("usage", {})

        # 记录 usage
        if usage:
            state["input_tokens"] = usage.get("prompt_tokens", state["input_tokens"])
            state["output_tokens"] = usage.get("completion_tokens", state["output_tokens"])

        # 消息开始（仅一次）
        if not state["started"]:
            state["started"] = True
            events.append(self._build_anthropic_sse("message_start", {
                "type": "message_start",
                "message": {
                    "id": state["msg_id"],
                    "type": "message",
                    "role": "assistant",
                    "model": state["model"],
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            }))

        # 文本增量
        text_delta = delta.get("content", "")
        if text_delta:
            idx = state["content_index"]
            if not state["sent_text_block_start"]:
                state["sent_text_block_start"] = True
                events.append(self._build_anthropic_sse("content_block_start", {
                    "type": "content_block_start",
                    "index": idx,
                    "content_block": {"type": "text", "text": ""},
                }))
            events.append(self._build_anthropic_sse("content_block_delta", {
                "type": "content_block_delta",
                "index": idx,
                "delta": {"type": "text_delta", "text": text_delta},
            }))

        # 工具调用增量
        tool_calls = delta.get("tool_calls", [])
        for tc in tool_calls:
            tc_index = tc.get("index", 0)
            tc_id = tc.get("id")
            tc_func = tc.get("function", {})
            tc_name = tc_func.get("name")
            tc_args = tc_func.get("arguments", "")

            if tc_index not in state["pending_tool_calls"]:
                state["pending_tool_calls"][tc_index] = {"id": "", "name": "", "arguments": ""}

            pending = state["pending_tool_calls"][tc_index]
            if tc_id:
                pending["id"] = tc_id
            if tc_name:
                pending["name"] = tc_name
            pending["arguments"] += tc_args

            # 如果尚未为此 tool 发送过 content_block_start
            if tc_index not in state["sent_tool_blocks"] and pending["name"]:
                state["sent_tool_blocks"].add(tc_index)
                events.append(self._build_anthropic_sse("content_block_start", {
                    "type": "content_block_start",
                    "index": tc_index,
                    "content_block": {
                        "type": "tool_use",
                        "id": pending["id"],
                        "name": pending["name"],
                        "input": {},
                    },
                }))

            if tc_args:
                events.append(self._build_anthropic_sse("content_block_delta", {
                    "type": "content_block_delta",
                    "index": tc_index,
                    "delta": {"type": "input_json_delta", "partial_json": tc_args},
                }))

        # 完成
        if finish_reason:
            # 先停止所有 content blocks
            for idx in range(state["content_index"] + len(state["pending_tool_calls"])):
                events.append(self._build_anthropic_sse("content_block_stop", {
                    "type": "content_block_stop",
                    "index": idx,
                }))

            # 修正: 使用上一次 content_block_stop 的 index（实际存在的 index）
            max_content_idx = len(state["pending_tool_calls"]) - 1 if state["pending_tool_calls"] else 0

            # 解析 tool_use 完成的数据
            for tc_index, pending in state["pending_tool_calls"].items():
                try:
                    parsed = json.loads(pending["arguments"])
                except (json.JSONDecodeError, ValueError):
                    parsed = {}
                events.append(self._build_anthropic_sse("content_block_start", {
                    "type": "content_block_start",
                    "index": tc_index,
                    "content_block": {
                        "type": "tool_use",
                        "id": pending["id"],
                        "name": pending["name"],
                        "input": parsed,
                    },
                }))

            mapped_stop = finish_reason
            if finish_reason in ("stop", "length"):
                mapped_stop = "end_turn"
            elif finish_reason == "tool_calls":
                mapped_stop = "tool_use"

            events.append(self._build_anthropic_sse("message_delta", {
                "type": "message_delta",
                "delta": {"stop_reason": mapped_stop, "stop_sequence": None},
                "usage": {"output_tokens": state["output_tokens"]},
            }))

        return events

    def _build_stream_end_events(self, state: dict) -> list[str]:
        """构建流结束时的收尾事件"""
        events: list[str] = []
        if state["finished"]:
            return events
        events.append(self._build_anthropic_sse("message_stop", {"type": "message_stop"}))
        return events

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _upstream_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.upstream_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }

    def _chat_completions_url(self) -> str:
        """构造上游 chat/completions URL。

        兼容 upstream_base_url 是否已含 /v1：
          - 含 /v1（如 DashScope compatible-mode .../v1）→ 只追加 /chat/completions
          - 不含 /v1（如 https://api.openai.com）→ 追加 /v1/chat/completions
        避免 /v1/v1/chat/completions 双重路径导致上游 400。
        """
        base = self.upstream_base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    @staticmethod
    def _build_anthropic_sse(event: str, data: dict) -> str:
        """构建 Anthropic 风格的 SSE 事件字符串"""
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def _build_anthropic_sse_data(data: dict) -> str:
        """构建无 event 类型的 data-only SSE 字符串"""
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
