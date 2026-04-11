from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Tuple


@dataclass
class AgentConfig:
    llm_provider: str = 'anthropic'
    llm_api_key: str = ''
    llm_model: str = 'claude-sonnet-4-20250514'
    llm_base_url: str = ''
    llm_max_tokens: int = 1024
    enabled_tools: Tuple[str, ...] = ('read_file', 'write_file', 'git_run')

    def __post_init__(self) -> None:
        if not self.llm_provider:
            self.llm_provider = os.getenv('LLM_PROVIDER', 'anthropic')
        if not self.llm_api_key:
            self.llm_api_key = os.getenv('LLM_API_KEY') or os.getenv('ANTHROPIC_API_KEY', '')
        if not self.llm_model:
            self.llm_model = os.getenv('LLM_MODEL') or os.getenv(
                'ANTHROPIC_MODEL', 'claude-sonnet-4-20250514'
            )
        if not self.llm_base_url:
            self.llm_base_url = os.getenv('LLM_BASE_URL', '')

    @property
    def anthropic_api_key(self) -> str:
        return self.llm_api_key

    @property
    def anthropic_model(self) -> str:
        return self.llm_model

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)
