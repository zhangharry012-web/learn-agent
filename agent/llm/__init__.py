from __future__ import annotations

from typing import Callable, Dict

from agent.config import DEFAULT_PROVIDER, PROVIDER_CLASS_ALIASES
from agent.llm.anthropic_client import AnthropicLLM
from agent.llm.base import BaseLLMClient, extract_text
from agent.llm.openai_client import OpenAICompatibleLLM
from agent.llm.types import LLMResponse, ToolCall, ToolResult

LLM_FACTORY_BY_PROVIDER_CLASS: Dict[str, Callable[..., BaseLLMClient]] = {
    DEFAULT_PROVIDER: AnthropicLLM,
    'openai-compatible': OpenAICompatibleLLM,
}


def create_llm(
    *,
    provider: str,
    api_key: str,
    model: str,
    max_tokens: int = 1024,
    base_url: str = '',
) -> BaseLLMClient:
    provider_class = PROVIDER_CLASS_ALIASES.get(provider)
    if provider_class is None:
        raise ValueError(f'Unsupported LLM provider: {provider}')
    factory = LLM_FACTORY_BY_PROVIDER_CLASS[provider_class]
    return factory(
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        base_url=base_url,
    )


__all__ = [
    'AnthropicLLM',
    'BaseLLMClient',
    'LLMResponse',
    'OpenAICompatibleLLM',
    'ToolCall',
    'ToolResult',
    'create_llm',
    'extract_text',
]
