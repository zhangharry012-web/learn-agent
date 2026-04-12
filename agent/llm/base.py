from __future__ import annotations

from typing import Any, Dict, List

from agent.llm.types import LLMResponse


class BaseLLMClient:
    def generate(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        raise NotImplementedError


def extract_text(response: LLMResponse) -> str:
    return response.text.strip()
