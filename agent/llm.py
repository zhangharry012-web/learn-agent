from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    import anthropic
except ImportError:  # pragma: no cover - exercised when dependency is missing
    anthropic = None


Message = Dict[str, Any]
ContentBlock = Dict[str, Any]


@dataclass
class LLMResponse:
    content: List[ContentBlock]
    stop_reason: str


class BaseLLMClient:
    def generate(
        self,
        *,
        system_prompt: str,
        messages: List[Message],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        raise NotImplementedError


class AnthropicLLM(BaseLLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
    ) -> None:
        if anthropic is None:
            raise RuntimeError(
                "The 'anthropic' package is not installed. Run 'pip install -r requirements.txt'."
            )

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def generate(
        self,
        *,
        system_prompt: str,
        messages: List[Message],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )
        return LLMResponse(
            content=[_block_to_dict(block) for block in response.content],
            stop_reason=response.stop_reason or "end_turn",
        )


def _block_to_dict(block: Any) -> ContentBlock:
    if hasattr(block, "model_dump"):
        return block.model_dump()

    if isinstance(block, dict):
        return block

    data: Dict[str, Any] = {}
    for field in ("type", "text", "id", "name", "input"):
        if hasattr(block, field):
            data[field] = getattr(block, field)
    return data


def extract_text(content: List[ContentBlock]) -> str:
    parts: List[str] = []
    for block in content:
        if block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts).strip()
