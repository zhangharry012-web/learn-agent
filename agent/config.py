from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Mapping, Tuple

DEFAULT_PROVIDER = 'anthropic'
DEFAULT_MODEL = 'claude-sonnet-4-20250514'
SUPPORTED_OPENAI_COMPATIBLE_PROVIDERS: FrozenSet[str] = frozenset(
    {'openai', 'deepseek', 'openai-compatible'}
)


@dataclass
class AgentConfig:
    llm_provider: str = field(default_factory=lambda: os.getenv('LLM_PROVIDER', DEFAULT_PROVIDER))
    llm_api_key: str = field(
        default_factory=lambda: os.getenv('LLM_API_KEY') or os.getenv('ANTHROPIC_API_KEY', '')
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv('LLM_MODEL') or os.getenv('ANTHROPIC_MODEL', DEFAULT_MODEL)
    )
    llm_base_url: str = field(default_factory=lambda: os.getenv('LLM_BASE_URL', ''))
    llm_max_tokens: int = 1024
    enabled_tools: Tuple[str, ...] = ('read_file', 'write_file', 'git_run')

    @property
    def anthropic_api_key(self) -> str:
        return self.llm_api_key

    @property
    def anthropic_model(self) -> str:
        return self.llm_model

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


PROVIDER_CLASS_ALIASES: Mapping[str, str] = {
    DEFAULT_PROVIDER: 'anthropic',
    'openai': 'openai-compatible',
    'deepseek': 'openai-compatible',
    'openai-compatible': 'openai-compatible',
}
