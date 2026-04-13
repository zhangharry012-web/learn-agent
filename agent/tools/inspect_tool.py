from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Mapping

from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.types import ToolExecutionResult


ALLOWED_INSPECT_ACTIONS = ('pwd', 'ls', 'find', 'du')
DEFAULT_FIND_MAX_DEPTH = 3
DEFAULT_LS_MAX_ENTRIES = 200
DEFAULT_FIND_MAX_ENTRIES = 200
DEFAULT_DU_MAX_ENTRIES = 200


class InspectPathTool(BaseTool):
    name = 'inspect_path'
    description = (
        'Inspect workspace directories with a small set of safe read-only actions. '
        'Supports pwd, ls, find, and du style directory inspection without arbitrary shell execution '
        'and does not require human approval.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'action': {
                'type': 'string',
                'enum': list(ALLOWED_INSPECT_ACTIONS),
                'description': 'Read-only inspection action to run: pwd, ls, find, or du.',
            },
            'path': {
                'type': 'string',
                'description': 'Optional relative path inside the workspace. Defaults to the workspace root.',
            },
            'include_hidden': {
                'type': 'boolean',
                'description': 'Whether hidden entries should be included for ls/find results.',
            },
            'max_depth': {
                'type': 'integer',
                'description': 'Optional recursion depth for find. Defaults to 3.',
            },
            'limit': {
                'type': 'integer',
                'description': 'Optional entry limit for ls/find/du results.',
            },
        },
        'required': ['action'],
    }

    def __init__(self, workspace_root: Path, shell_runner: ShellRunner) -> None:
        super().__init__(workspace_root)
        self.shell_runner = shell_runner

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            action = str(payload['action'])
            if action not in ALLOWED_INSPECT_ACTIONS:
                return ToolExecutionResult(ok=False, content='Unsupported inspect action.')
            if action == 'pwd':
                return self._run_pwd()
            target = self._resolve_target(payload)
            if action == 'ls':
                return self._run_ls(target, payload)
            if action == 'find':
                return self._run_find(target, payload)
            return self._run_du(target, payload)
        except Exception as exc:
            return ToolExecutionResult(ok=False, content=str(exc))

    def _resolve_target(self, payload: Mapping[str, Any]) -> Path:
        raw_path = str(payload.get('path') or '.')
        target = self.resolve_path(raw_path)
        if not target.exists():
            raise ValueError('Target path does not exist.')
        return target

    def _run_pwd(self) -> ToolExecutionResult:
        return self._json_result(ok=True, payload={'action': 'pwd', 'path': '.', 'stdout': '.', 'stderr': ''})

    def _run_ls(self, target: Path, payload: Mapping[str, Any]) -> ToolExecutionResult:
        argv = ['ls', '-1']
        if bool(payload.get('include_hidden', False)):
            argv.append('-A')
        argv.append(str(target))
        result = self.shell_runner.run_argv(argv, cwd=self.workspace_root)
        lines = self._limited_lines(result.stdout, self._bounded_limit(payload.get('limit'), DEFAULT_LS_MAX_ENTRIES))
        return self._json_result(
            result.ok,
            {
                'action': 'ls',
                'path': str(target.relative_to(self.workspace_root)),
                'entries': lines,
                'stderr': result.stderr,
            },
        )

    def _run_find(self, target: Path, payload: Mapping[str, Any]) -> ToolExecutionResult:
        max_depth = self._bounded_depth(payload.get('max_depth'))
        argv = ['find', str(target), '-maxdepth', str(max_depth)]
        if not bool(payload.get('include_hidden', False)):
            argv.extend(['!', '-path', '*/.*'])
        result = self.shell_runner.run_argv(argv, cwd=self.workspace_root)
        lines = self._limited_lines(result.stdout, self._bounded_limit(payload.get('limit'), DEFAULT_FIND_MAX_ENTRIES))
        normalized = [self._normalize_output_path(line) for line in lines if line]
        return self._json_result(
            result.ok,
            {
                'action': 'find',
                'path': str(target.relative_to(self.workspace_root)),
                'max_depth': max_depth,
                'entries': normalized,
                'stderr': result.stderr,
            },
        )

    def _run_du(self, target: Path, payload: Mapping[str, Any]) -> ToolExecutionResult:
        argv = ['du', '-h', '-d', '1', str(target)]
        result = self.shell_runner.run_argv(argv, cwd=self.workspace_root)
        lines = self._limited_lines(result.stdout, self._bounded_limit(payload.get('limit'), DEFAULT_DU_MAX_ENTRIES))
        return self._json_result(
            result.ok,
            {
                'action': 'du',
                'path': str(target.relative_to(self.workspace_root)),
                'entries': lines,
                'stderr': result.stderr,
            },
        )

    def _bounded_depth(self, raw_depth: Any) -> int:
        if raw_depth is None:
            return DEFAULT_FIND_MAX_DEPTH
        depth = int(raw_depth)
        if depth < 0:
            return 0
        return min(depth, 10)

    def _bounded_limit(self, raw_limit: Any, default: int) -> int:
        if raw_limit is None:
            return default
        limit = int(raw_limit)
        if limit <= 0:
            return default
        return min(limit, default)

    def _limited_lines(self, stdout: str, limit: int) -> List[str]:
        lines = [line for line in stdout.splitlines() if line]
        return lines[:limit]

    def _normalize_output_path(self, raw: str) -> str:
        path = Path(raw)
        try:
            return str(path.resolve().relative_to(self.workspace_root))
        except Exception:
            return raw

    def _json_result(self, ok: bool, payload: Mapping[str, Any]) -> ToolExecutionResult:
        return ToolExecutionResult(ok=ok, content=json.dumps(dict(payload), ensure_ascii=False))
