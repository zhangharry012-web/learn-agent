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
        '- read_file: read file contents (supports line ranges).\n'
        '- write_file: create new files, full rewrites, or delete files (mode=delete).\n'
        '- edit_file: focused search-and-replace edits to existing files.\n'
        '- inspect_path: workspace layout (pwd, ls, find, du) and lightweight file metadata (head, tail, wc, stat, file).\n'
        '- verify_command: test, lint, build, and TS execution commands (e.g., python -m unittest, '
        'npm test, npx ts-node file.ts, npx tsx file.ts). Use after code changes to validate.\n'
        '- exec: arbitrary shell commands not covered above. Requires human approval.\n'
        '\n'
        'EFFICIENCY RULES:\n'
        '- Batch related inspections in one turn: use inspect_path once with find or ls to discover '
        'the project layout, then read key config files (package.json, tsconfig.json, pyproject.toml) '
        'in the same turn. Never call inspect_path with pwd alone — it returns no useful information. '
        'Use ls or find instead.\n'
        '- When the user specifies an exact file path to create or modify, write the file directly '
        'without inspecting the directory first. Only inspect when the target location is ambiguous.\n'
        '- Before writing code to an unspecified location, inspect the project structure first to '
        'determine the correct language, framework, and file location. '
        'Never assume the project language without checking.\n'
        '- When generating code, strictly use the target language\'s native comment and documentation '
        'syntax. Never mix comment styles across languages.\n'
        '- Do not create temporary test files when you can use verify_command to run the project\'s '
        'existing test suite instead. If you must create a temp file, delete it via write_file '
        'mode=delete when done — do not use exec rm.\n'
        '\n'
        'GENERAL RULES:\n'
        '- Never request more than one approval-required tool call in the same response.\n'
        '- Summarize results clearly after tool execution.\n'
        '- Each tool loop has a limited step budget — be efficient with tool calls.'
    )
