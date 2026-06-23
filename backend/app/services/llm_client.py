"""
LLM Client - 大模型调用客户端
支持多种 LLM 提供商：OpenAI, Anthropic, 通义千问
API Key 从数据库配置中获取，不再依赖环境变量
"""
import asyncio
import logging
import time
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)


class LLMResult:
    """LLM 调用结果"""
    def __init__(
        self,
        content: str,
        prompt_tokens: int,
        completion_tokens: int,
        generation_time: int,
    ):
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.generation_time = generation_time


class LLMError(Exception):
    """LLM 调用错误"""
    pass


class BaseLLMClient:
    """LLM 客户端基类"""

    def __init__(self, api_key: str, api_base: Optional[str] = None):
        self.api_key = api_key
        self.api_base = api_base

    async def generate(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResult:
        raise NotImplementedError

    async def generate_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        raise NotImplementedError


class OpenAIClient(BaseLLMClient):
    """OpenAI API 客户端"""

    async def generate(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResult:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.openai.com/v1"
            )

            start_time = time.time()
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            generation_time = int(time.time() - start_time)

            return LLMResult(
                content=response.choices[0].message.content or "",
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                generation_time=generation_time,
            )
        except Exception as e:
            logger.error(f"OpenAI API call failed: {e}")
            raise LLMError(f"OpenAI API call failed: {str(e)}")

    async def generate_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.openai.com/v1"
            )

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )

            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"OpenAI streaming failed: {e}")
            raise LLMError(f"OpenAI streaming failed: {str(e)}")


class AnthropicClient(BaseLLMClient):
    """Anthropic API 客户端"""

    async def generate(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResult:
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.anthropic.com"
            )

            start_time = time.time()

            # Anthropic 的 API 格式不同
            system_prompt = ""
            user_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_prompt = msg["content"]
                else:
                    user_messages.append(msg)

            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=user_messages,
            )
            generation_time = int(time.time() - start_time)

            return LLMResult(
                content=response.content[0].text if response.content else "",
                prompt_tokens=response.usage.input_tokens if response.usage else 0,
                completion_tokens=response.usage.output_tokens if response.usage else 0,
                generation_time=generation_time,
            )
        except Exception as e:
            logger.error(f"Anthropic API call failed: {e}")
            raise LLMError(f"Anthropic API call failed: {str(e)}")

    async def generate_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(
                api_key=self.api_key,
                base_url=self.api_base or "https://api.anthropic.com"
            )

            system_prompt = ""
            user_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    system_prompt = msg["content"]
                else:
                    user_messages.append(msg)

            async with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=user_messages,
                temperature=temperature,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as e:
            logger.error(f"Anthropic streaming failed: {e}")
            raise LLMError(f"Anthropic streaming failed: {str(e)}")


class QwenClient(BaseLLMClient):
    """通义千问 API 客户端（兼容 OpenAI 格式）"""

    async def generate(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResult:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )

            start_time = time.time()
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            generation_time = int(time.time() - start_time)

            return LLMResult(
                content=response.choices[0].message.content or "",
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                generation_time=generation_time,
            )
        except Exception as e:
            logger.error(f"Qwen API call failed: {e}")
            raise LLMError(f"Qwen API call failed: {str(e)}")

    async def generate_stream(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base or "https://dashscope.aliyuncs.com/compatible-mode/v1"
            )

            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )

            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"Qwen streaming failed: {e}")
            raise LLMError(f"Qwen streaming failed: {str(e)}")


# 提供商对应的客户端类
PROVIDER_CLIENTS = {
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
    "qwen": QwenClient,
}


def create_client(provider: str, api_key: str, api_base: Optional[str] = None) -> BaseLLMClient:
    """
    创建 LLM 客户端实例

    Args:
        provider: 提供商名称 (openai/anthropic/qwen)
        api_key: API Key
        api_base: API 基础 URL（可选）

    Returns:
        LLM 客户端实例
    """
    if provider not in PROVIDER_CLIENTS:
        raise LLMError(f"Unsupported provider: {provider}. Available: {list(PROVIDER_CLIENTS.keys())}")

    client_class = PROVIDER_CLIENTS[provider]
    return client_class(api_key=api_key, api_base=api_base)


class LLMClient:
    """LLM 调用客户端（统一入口）- 支持动态传入配置"""

    async def generate(
        self,
        provider: str,
        model: str,
        api_key: str,
        api_base: Optional[str] = None,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResult:
        """
        调用大模型生成内容

        Args:
            provider: LLM 提供商 (openai/anthropic/qwen)
            model: 模型名称
            api_key: API Key
            api_base: API 基础 URL（可选）
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            LLMResult 对象
        """
        if not api_key:
            raise LLMError(f"API Key not configured for provider: {provider}")

        client = create_client(provider, api_key, api_base)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return await client.generate(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def generate_stream(
        self,
        provider: str,
        model: str,
        api_key: str,
        api_base: Optional[str] = None,
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        if not api_key:
            raise LLMError(f"API Key not configured for provider: {provider}")

        client = create_client(provider, api_key, api_base)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        async for chunk in client.generate_stream(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            yield chunk

    def get_supported_providers(self) -> list[str]:
        """获取支持的 LLM 提供商列表"""
        return list(PROVIDER_CLIENTS.keys())