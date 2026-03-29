from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Tuple


@dataclass
class AgentConfig:
    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    anthropic_model: str = field(
        default_factory=lambda: os.getenv(
            "ANTHROPIC_MODEL", "claude-sonnet-4-20250514"
        )
    )
    llm_max_tokens: int = 1024
    enabled_tools: Tuple[str, ...] = ("read_file", "write_file", "git_run")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)
