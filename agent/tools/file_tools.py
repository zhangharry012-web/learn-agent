from __future__ import annotations

import json
from typing import Any, Mapping

from agent.tools.base import BaseTool
from agent.tools.types import ToolExecutionResult


class ReadFileTool(BaseTool):
    name = 'read_file'
    description = (
        'Read a local text file from the current workspace. Use this tool whenever you need '
        'to inspect project files before answering or taking action. This tool is read-only '
        'and does not require human approval. Prefer relative paths rooted in the project.'
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
        'Write text to a local file in the current workspace. Use this tool only when the user '
        'explicitly wants file content created or modified. This tool always requires human '
        'approval before execution. The mode can be overwrite or append.'
    )
    requires_approval = True
    input_schema = {
        'type': 'object',
        'properties': {
            'path': {
                'type': 'string',
                'description': 'Relative path to the file to write.',
            },
            'content': {
                'type': 'string',
                'description': 'Full text content to write.',
            },
            'mode': {
                'type': 'string',
                'enum': ['overwrite', 'append'],
                'description': 'Whether to replace the file or append to it.',
            },
        },
        'required': ['path', 'content', 'mode'],
    }

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            path = self.resolve_path(str(payload['path']))
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = str(payload['mode'])
            content = str(payload['content'])
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
        return (
            'Approve file write? '
            f"path={payload.get('path')} mode={payload.get('mode')} "
            f"bytes={len(str(payload.get('content', '')).encode('utf-8'))}"
        )
