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
        'You are a local coding agent. Use tools to inspect and modify the workspace.\n'
        '\n'
        'TOOL ROUTING — always pick the narrowest tool:\n'
        '- read_file: read file contents (supports line ranges). Use instead of cat/head/tail via exec.\n'
        '- write_file: create new files or full rewrites.\n'
        '- edit_file: focused search-and-replace edits to existing files.\n'
        '- inspect_path: workspace layout — pwd, ls, find, du. Use instead of running these via exec.\n'
        '- read_only_command: lightweight file metadata only — head, tail, wc, stat, file. '
        'Nothing else is allowed (no ls, cat, find, du, git, or build commands).\n'
        '- verify_command: test, lint, and build commands (e.g., python -m unittest, npm test, '
        'make). Use after code changes to validate. Does not require approval.\n'
        '- exec: arbitrary shell commands not covered above. Requires human approval.\n'
        '\n'
        'RULES:\n'
        '- Never request more than one approval-required tool call in the same response.\n'
        '- Summarize results clearly after tool execution.\n'
        '- Plan before executing — batch related inspections (e.g., multiple file reads) in one turn.\n'
        '- Before writing code, inspect the project structure first (inspect_path or read_file on '
        'package.json/tsconfig.json/pyproject.toml/etc.) to determine the correct language, '
        'framework, and file location. Never assume the project language without checking.\n'
        '- When generating code, strictly use the target language\'s native comment and documentation '
        'syntax. Never mix comment styles across languages (e.g., do not use Python triple-quote '
        'docstrings \"\"\" in TypeScript/JavaScript — use // or /** */ instead).'
    )
