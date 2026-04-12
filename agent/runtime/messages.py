from __future__ import annotations

from typing import Any, Dict, List

from agent.llm import ToolResult


def build_assistant_message(text: str, tool_calls: List[Any]) -> Dict[str, Any]:
    return {
        'role': 'assistant',
        'text': text,
        'tool_calls': tool_calls,
    }


def build_tool_result_message(tool_results: List[ToolResult]) -> Dict[str, Any]:
    return {
        'role': 'tool_result',
        'results': tool_results,
    }


def build_system_prompt() -> str:
    return (
        'You are a shell-oriented local coding agent. Use tools to inspect and modify the local '
        'workspace. Prefer reading files before making claims about file contents. Only request '
        'write_file when the user wants to create or edit local files. Only request git_run when '
        'you need repository information or git actions. Never request more than one approval-'
        'required tool call in the same response. If a write_file or git_run action is needed, '
        'request it and wait for approval. Summarize results clearly after tool execution.'
    )
