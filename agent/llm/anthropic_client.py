from __future__ import annotations

from typing import Any, Dict, List

from agent.llm.base import BaseLLMClient
from agent.llm.types import LLMResponse, ToolCall

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None


class AnthropicLLM(BaseLLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
        base_url: str = "",
    ) -> None:
        if anthropic is None:
            raise RuntimeError(
                "The 'anthropic' package is not installed. Run 'pip install -r requirements.txt'."
            )

        client_kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.client = anthropic.Anthropic(**client_kwargs)
        self.model = model
        self.max_tokens = max_tokens

    def generate(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            tools=self._to_anthropic_tools(tools),
            messages=self._to_anthropic_messages(messages),
        )
        return self._parse_response(response)

    def _to_anthropic_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        converted: List[Dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            if role == "user":
                converted.append({"role": "user", "content": message["content"]})
                continue
            if role == "assistant":
                content: List[Dict[str, Any]] = []
                text = message.get("text", "")
                if text:
                    content.append({"type": "text", "text": text})
                for tool_call in message.get("tool_calls", []):
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "input": tool_call.arguments,
                        }
                    )
                converted.append({"role": "assistant", "content": content})
                continue
            if role == "tool_result":
                content: List[Dict[str, Any]] = []
                for result in message["results"]:
                    content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": result.tool_call_id,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                    )
                converted.append({"role": "user", "content": content})
                continue
            raise ValueError(f"Unsupported message role: {role}")
        return converted

    def _to_anthropic_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return tools

    def _parse_response(self, response: Any) -> LLMResponse:
        text_parts: List[str] = []
        tool_calls: List[ToolCall] = []
        for block in response.content:
            data = _block_to_dict(block)
            if data.get("type") == "text" and data.get("text"):
                text_parts.append(str(data["text"]))
            if data.get("type") == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=str(data["id"]),
                        name=str(data["name"]),
                        arguments=dict(data.get("input") or {}),
                    )
                )
        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
            stop_reason=_normalize_anthropic_stop_reason(getattr(response, "stop_reason", None)),
        )


def _block_to_dict(block: Any) -> Dict[str, Any]:
    if hasattr(block, "model_dump"):
        return block.model_dump()
    if isinstance(block, dict):
        return block
    data: Dict[str, Any] = {}
    for field in ("type", "text", "id", "name", "input"):
        if hasattr(block, field):
            data[field] = getattr(block, field)
    return data


def _normalize_anthropic_stop_reason(stop_reason: Any) -> str:
    if stop_reason == "tool_use":
        return "tool_use"
    if stop_reason == "max_tokens":
        return "max_tokens"
    if stop_reason == "end_turn" or stop_reason is None:
        return "end_turn"
    return "other"
