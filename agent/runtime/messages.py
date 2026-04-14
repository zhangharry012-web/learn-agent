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
        'workspace. Prefer read_file before making claims about file contents. Use edit_file for '
        'focused in-place edits to existing files. Use write_file for creating files or broad '
        'rewrites. Use git_run only for git operations. Use exec for direct shell commands such '
        'as inspection, validation, or local execution. Never request more than one approval-'
        'required tool call in the same response. If an approval-required action is needed, '
        'request it and wait for approval. Summarize results clearly after tool execution.'
    )
