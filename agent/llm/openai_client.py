from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from agent.llm.base import BaseLLMClient
from agent.llm.types import LLMResponse, TokenUsage, ToolCall

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None


class OpenAICompatibleLLM(BaseLLMClient):
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
        base_url: str = '',
    ) -> None:
        if OpenAI is None:
            raise RuntimeError(
                "The 'openai' package is not installed. Run 'pip install -r requirements.txt'."
            )

        client_kwargs: Dict[str, Any] = {'api_key': api_key}
        if base_url:
            client_kwargs['base_url'] = base_url
        self.client = OpenAI(**client_kwargs)
        self.model = model
        self.max_tokens = max_tokens

    def generate(
        self,
        *,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=self._to_openai_messages(system_prompt, messages),
            tools=self._to_openai_tools(tools),
        )
        return self._parse_response(response)

    def _to_openai_messages(
        self, system_prompt: str, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        converted: List[Dict[str, Any]] = [{'role': 'system', 'content': system_prompt}]
        for message in messages:
            role = message['role']
            if role == 'user':
                converted.append({'role': 'user', 'content': message['content']})
                continue
            if role == 'assistant':
                entry: Dict[str, Any] = {
                    'role': 'assistant',
                    'content': message.get('text', '') or '',
                }
                tool_calls = []
                for tool_call in message.get('tool_calls', []):
                    tool_calls.append(
                        {
                            'id': tool_call.id,
                            'type': 'function',
                            'function': {
                                'name': tool_call.name,
                                'arguments': json.dumps(tool_call.arguments),
                            },
                        }
                    )
                if tool_calls:
                    entry['tool_calls'] = tool_calls
                converted.append(entry)
                continue
            if role == 'tool_result':
                for result in message['results']:
                    converted.append(
                        {
                            'role': 'tool',
                            'tool_call_id': result.tool_call_id,
                            'content': result.content,
                        }
                    )
                continue
            raise ValueError(f'Unsupported message role: {role}')
        return converted

    def _to_openai_tools(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        converted = []
        for tool in tools:
            converted.append(
                {
                    'type': 'function',
                    'function': {
                        'name': tool['name'],
                        'description': tool.get('description', ''),
                        'parameters': tool['input_schema'],
                    },
                }
            )
        return converted

    def _parse_response(self, response: Any) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message
        tool_calls: List[ToolCall] = []
        for tool_call in getattr(message, 'tool_calls', []) or []:
            arguments = getattr(tool_call.function, 'arguments', '')
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise ValueError('Invalid tool arguments from provider') from exc
            if not isinstance(parsed, dict):
                raise ValueError('Invalid tool arguments from provider')
            tool_calls.append(
                ToolCall(
                    id=str(tool_call.id),
                    name=str(tool_call.function.name),
                    arguments=parsed,
                )
            )
        text = message.content or ''
        return LLMResponse(
            text=text.strip(),
            tool_calls=tool_calls,
            stop_reason=_normalize_openai_stop_reason(getattr(choice, 'finish_reason', None)),
            usage=_extract_openai_usage(getattr(response, 'usage', None)),
        )


def _normalize_openai_stop_reason(stop_reason: Any) -> str:
    if stop_reason == 'tool_calls':
        return 'tool_use'
    if stop_reason == 'length':
        return 'max_tokens'
    if stop_reason == 'stop' or stop_reason is None:
        return 'end_turn'
    return 'other'


def _extract_openai_usage(usage: Any) -> Optional[TokenUsage]:
    if usage is None:
        return None
    input_tokens = int(getattr(usage, 'prompt_tokens', 0) or 0)
    output_tokens = int(getattr(usage, 'completion_tokens', 0) or 0)
    total_tokens = int(getattr(usage, 'total_tokens', 0) or (input_tokens + output_tokens))
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
