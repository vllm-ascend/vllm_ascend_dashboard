"""Compatibility and bounded-memory runtime for tool-calling agents."""

from __future__ import annotations

import ast
import copy
import json
import logging
import re
import time
from typing import Any

from smolagents import LiteLLMModel, ToolCallingAgent
from smolagents.models import (
    ChatMessage,
    ChatMessageToolCall,
    ChatMessageToolCallFunction,
    MessageRole,
)

logger = logging.getLogger(__name__)


def _literal_candidates(text: str) -> list[Any]:
    """Safely recover JSON/Python literals embedded in explanatory text."""
    candidates: list[Any] = []
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        suffix = text[index:].strip()
        try:
            value, _ = decoder.raw_decode(suffix)
            candidates.append(value)
        except (json.JSONDecodeError, TypeError):
            pass
        # GLM sometimes mirrors smolagents' Python repr with single quotes.
        # literal_eval is data-only and does not execute expressions.
        for end in range(len(suffix), 1, -1):
            if suffix[end - 1] not in "]}":
                continue
            try:
                candidates.append(ast.literal_eval(suffix[:end]))
                break
            except (ValueError, SyntaxError, MemoryError, RecursionError):
                continue
    return candidates


def recover_tool_calls(text: str, allowed_tools: set[str]) -> list[ChatMessageToolCall]:
    """Convert degraded textual calls into validated smolagents calls."""
    best: list[ChatMessageToolCall] = []
    for value in _literal_candidates(text or ""):
        items = value if isinstance(value, list) else [value]
        recovered: list[ChatMessageToolCall] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                recovered = []
                break
            function = item.get("function") if isinstance(item.get("function"), dict) else item
            name = function.get("name")
            arguments = function.get("arguments", item.get("arguments"))
            if arguments is None:
                # Some degraded responses put the sole argument beside name.
                arguments = {
                    key: val for key, val in function.items()
                    if key not in {"name", "id", "type", "function"}
                }
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    try:
                        arguments = ast.literal_eval(arguments)
                    except (ValueError, SyntaxError):
                        recovered = []
                        break
            if (
                not isinstance(name, str)
                or name not in allowed_tools
                or not isinstance(arguments, dict)
            ):
                recovered = []
                break
            recovered.append(ChatMessageToolCall(
                id=str(item.get("id") or f"recovered_call_{index + 1}"),
                type="function",
                function=ChatMessageToolCallFunction(name=name, arguments=arguments),
            ))
        if len(recovered) > len(best):
            best = recovered
    return best


class CompatibleLiteLLMModel(LiteLLMModel):
    """Preserve native calls and recover GLM calls degraded into text."""

    def __init__(
        self,
        *args,
        allowed_tools: set[str] | None = None,
        generation_retries: int = 1,
        action_timeout: int = 120,
        final_timeout: int = 240,
        **kwargs,
    ):
        self.allowed_tools = set(allowed_tools or ()) | {"final_answer"}
        self.generation_retries = max(0, min(int(generation_retries), 1))
        self.action_timeout = max(30, int(action_timeout))
        self.final_timeout = max(self.action_timeout, int(final_timeout))
        super().__init__(*args, **kwargs)

    def generate(self, *args, **kwargs) -> ChatMessage:
        tools = kwargs.get("tools_to_call_from")
        is_final_render = tools is None or (
            isinstance(tools, list)
            and tools
            and all(getattr(tool, "name", "") == "final_answer" for tool in tools)
        )
        previous_timeout = self.kwargs.get("timeout")
        timeout_seconds = self.final_timeout if is_final_render else self.action_timeout
        self.kwargs["timeout"] = timeout_seconds
        started = time.monotonic()
        logger.info(
            "Agent model call starting kind=%s timeout=%ss",
            "final" if is_final_render else "action",
            timeout_seconds,
        )
        for attempt in range(self.generation_retries + 1):
            try:
                message = super().generate(*args, **kwargs)
                logger.info(
                    "Agent model call finished kind=%s duration=%.1fs tool_calls=%s content_len=%s",
                    "final" if is_final_render else "action",
                    time.monotonic() - started,
                    len(message.tool_calls or []),
                    len(str(message.content or "")),
                )
                break
            except Exception as exc:
                logger.warning(
                    "Agent model call failed kind=%s duration=%.1fs error=%s",
                    "final" if is_final_render else "action",
                    time.monotonic() - started,
                    exc,
                )
                if _is_timeout_error(exc) and not is_final_render:
                    # ToolCallingAgent converts a response without a tool call
                    # into a recoverable parsing step and then continues with
                    # its intact memory. Do not repeat the same long inference.
                    logger.warning("Action model call timed out; advancing to next agent step")
                    message = ChatMessage(
                        role=MessageRole.ASSISTANT,
                        content="模型请求在产出工具调用前超时。请基于已有证据继续下一步，避免重复发起同样的大上下文请求。",
                    )
                    break
                if attempt >= self.generation_retries or not _is_transient_generation_error(exc):
                    if previous_timeout is None:
                        self.kwargs.pop("timeout", None)
                    else:
                        self.kwargs["timeout"] = previous_timeout
                    raise
                logger.warning(
                    "Transient model generation failure; retrying once: %s",
                    exc,
                )
        if previous_timeout is None:
            self.kwargs.pop("timeout", None)
        else:
            self.kwargs["timeout"] = previous_timeout
        if not message.tool_calls and isinstance(message.content, str):
            recovered = recover_tool_calls(message.content, self.allowed_tools)
            if recovered:
                # Textual JSON recovery is a compatibility fallback for models
                # that failed to emit native tool_calls.  Some runtimes execute
                # only one recovered call even if the text contains several;
                # keeping all of them in assistant content makes the next turn
                # believe unexecuted tools already ran.  Preserve native
                # parallel tool calls above, but make recovered calls honest
                # and single-step.
                recovered = recovered[:1]
                message.tool_calls = recovered
                message.content = "Calling tools (canonical JSON):\n" + json.dumps(
                    [
                        {
                            "id": call.id,
                            "type": call.type,
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in recovered
                    ],
                    ensure_ascii=False,
                )
        return message


def _is_transient_generation_error(exc: Exception) -> bool:
    """Retry only transport failures, never invalid prompts or model errors."""
    text = f"{exc.__class__.__name__}: {exc}".lower()
    return any(marker in text for marker in (
        "connectionerror",
        "connection error",
        "serviceunavailable",
        "service unavailable",
        "rate limit",
        "ratelimit",
        "temporarily unavailable",
    ))


def _is_timeout_error(exc: Exception) -> bool:
    text = f"{exc.__class__.__name__}: {exc}".lower()
    return "timeout" in text or "timed out" in text


class BoundedToolCallingAgent(ToolCallingAgent):
    """Use canonical JSON history and keep the active context bounded."""

    max_history_messages = 32
    max_history_chars = 180_000
    max_message_chars = 24_000

    def write_memory_to_messages(self, summary_mode: bool = False) -> list[ChatMessage]:
        messages = super().write_memory_to_messages(summary_mode=summary_mode)
        normalized = [self._normalize_message(message) for message in messages]
        if len(normalized) > self.max_history_messages:
            # Keep system + task anchors and the most recent investigation.
            normalized = normalized[:2] + normalized[-(self.max_history_messages - 2):]

        total = 0
        kept: list[ChatMessage] = []
        for message in reversed(normalized):
            size = len(str(message.content or ""))
            if kept and total + size > self.max_history_chars:
                continue
            kept.append(message)
            total += size
        kept.reverse()
        # System prompt must never be dropped by the character budget.
        if normalized and normalized[0] not in kept:
            kept.insert(0, normalized[0])
        return kept

    def _normalize_message(self, message: ChatMessage) -> ChatMessage:
        message = copy.deepcopy(message)
        content = message.content
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                    continue
                text = block["text"]
                if text.startswith("Calling tools:\n"):
                    calls = _literal_candidates(text.removeprefix("Calling tools:\n"))
                    if calls:
                        canonical = max(
                            calls,
                            key=lambda value: len(value) if isinstance(value, list) else 1,
                        )
                        text = "Calling tools (canonical JSON):\n" + json.dumps(
                            canonical, ensure_ascii=False, separators=(",", ":")
                        )
                if len(text) > self.max_message_chars:
                    text = text[: self.max_message_chars] + "\n...[history truncated]"
                block["text"] = text
        elif isinstance(content, str) and len(content) > self.max_message_chars:
            message.content = content[: self.max_message_chars] + "\n...[history truncated]"
        return message
