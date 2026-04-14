from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agent.tools.base import BaseTool
from agent.tools.types import ToolExecutionResult


class ReadFileTool(BaseTool):
    name = 'read_file'
    description = (
        'Read UTF-8 text file contents from the current workspace. '
        'Use this tool whenever you need the contents of a specific file, including cat/head/tail style tasks. '
        'Prefer start_line and end_line instead of shell commands when you only need part of a file. '
        'This tool is read-only, does not require human approval, and is restricted to the project root.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'Relative path to a UTF-8 text file in the workspace.',
            },
            'start_line': {
                'type': 'integer',
                'description': 'Optional 1-based starting line number.',
            },
            'end_line': {
                'type': 'integer',
                'description': 'Optional 1-based ending line number, inclusive.',
            },
        },
        'required': ['path'],
    }

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            path = self.resolve_path(str(payload['path']))
            content = path.read_text(encoding='utf-8')
            lines = content.splitlines()
            start_line = int(payload.get('start_line') or 1)
            end_line = int(payload.get('end_line') or len(lines))
            selected = lines[start_line - 1 : end_line]
            result = {
                'path': str(path.relative_to(self.workspace_root)),
                'start_line': start_line,
                'end_line': end_line,
                'content': chr(10).join(selected),
            }
            return ToolExecutionResult(ok=True, content=json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            return ToolExecutionResult(ok=False, content=str(exc))


class WriteFileTool(BaseTool):
    name = 'write_file'
    description = (
        'Write text to a local file in the current workspace, or delete a file. Use this tool only when the user '
        'explicitly wants file content created, modified, or removed. This tool executes immediately '
        'inside the project root and never writes outside that root. The mode can be overwrite, append, or delete. '
        'Use mode=delete to remove temporary or generated files without needing exec approval.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'Relative path to the file to write or delete.',
            },
            'content': {
                'type': 'string',
                'description': 'Full text content to write. Not required when mode is delete.',
            },
            'mode': {
                'type': 'string',
                'enum': ['overwrite', 'append', 'delete'],
                'description': 'Whether to replace the file, append to it, or delete it.',
            },
        },
        'required': ['path', 'mode'],
    }

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            path = self.resolve_path(str(payload['path']))
            mode = str(payload['mode'])
            if mode == 'delete':
                if not path.exists():
                    return ToolExecutionResult(ok=False, content='Target file does not exist.')
                path.unlink()
                result = {
                    'path': str(path.relative_to(self.workspace_root)),
                    'mode': 'delete',
                    'deleted': True,
                }
                return ToolExecutionResult(ok=True, content=json.dumps(result, ensure_ascii=False))
            path.parent.mkdir(parents=True, exist_ok=True)
            content = str(payload.get('content') or '')
            if mode == 'overwrite':
                path.write_text(content, encoding='utf-8')
            elif mode == 'append':
                with path.open('a', encoding='utf-8') as handle:
                    handle.write(content)
            else:
                return ToolExecutionResult(ok=False, content='Unsupported write mode.')

            result = {
                'path': str(path.relative_to(self.workspace_root)),
                'mode': mode,
                'bytes_written': len(content.encode('utf-8')),
            }
            return ToolExecutionResult(ok=True, content=json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            return ToolExecutionResult(ok=False, content=str(exc))

    def approval_prompt(self, payload: Mapping[str, Any]) -> str:
        mode = payload.get('mode')
        if mode == 'delete':
            return f"Approve file delete? path={payload.get('path')}"
        return (
            'Approve file write? '
            f"path={payload.get('path')} mode={mode} "
            f"bytes={len(str(payload.get('content', '')).encode('utf-8'))}"
        )


class EditFileTool(BaseTool):
    name = 'edit_file'
    description = (
        'Edit an existing local text file in the current workspace by replacing exact text. '
        'Use this tool for focused in-place updates instead of full rewrites when the change '
        'is a clear search-and-replace. This tool executes immediately and is restricted to the project root.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'Relative path to the existing file to edit.',
            },
            'search': {
                'type': 'string',
                'description': 'Exact text to find.',
            },
            'replace': {
                'type': 'string',
                'description': 'Replacement text.',
            },
            'replace_all': {
                'type': 'boolean',
                'description': 'Whether to replace all matches. Defaults to false.',
            },
        },
        'required': ['path', 'search', 'replace'],
    }

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            path = self.resolve_path(str(payload['path']))
            if not path.exists():
                return ToolExecutionResult(ok=False, content='Target file does not exist.')

            search = str(payload['search'])
            replace = str(payload['replace'])
            replace_all = bool(payload.get('replace_all', False))

            if not search:
                return ToolExecutionResult(ok=False, content='Search text must not be empty.')

            original = path.read_text(encoding='utf-8')
            matches = original.count(search)
            if matches == 0:
                return ToolExecutionResult(ok=False, content='Search text was not found in the file.')

            if replace_all:
                updated = original.replace(search, replace)
                replacements = matches
            else:
                updated = original.replace(search, replace, 1)
                replacements = 1

            path.write_text(updated, encoding='utf-8')
            result = {
                'path': str(path.relative_to(self.workspace_root)),
                'replacements': replacements,
                'replace_all': replace_all,
            }
            return ToolExecutionResult(ok=True, content=json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            return ToolExecutionResult(ok=False, content=str(exc))

    def approval_prompt(self, payload: Mapping[str, Any]) -> str:
        replace_all = bool(payload.get('replace_all', False))
        scope = 'all matches' if replace_all else 'first match'
        return f"Approve file edit? path={payload.get('path')} scope={scope}"
