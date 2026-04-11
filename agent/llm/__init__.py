from agent.llm.anthropic_client import AnthropicLLM
from agent.llm.base import BaseLLMClient, extract_text
from agent.llm.openai_client import OpenAICompatibleLLM
from agent.llm.types import LLMResponse, ToolCall, ToolResult


def create_llm(*, provider: str, api_key: str, model: str, max_tokens: int = 1024, base_url: str = '') -> BaseLLMClient:
    if provider == 'anthropic':
        return AnthropicLLM(
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            base_url=base_url,
        )
    if provider in {'openai', 'deepseek', 'openai-compatible'}:
        return OpenAICompatibleLLM(
            api_key=api_key,
            model=model,
            max_tokens=max_tokens,
            base_url=base_url,
        )
    raise ValueError(f'Unsupported LLM provider: {provider}')


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
