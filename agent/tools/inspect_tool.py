from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, List, Mapping

from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.types import ToolExecutionResult


ALLOWED_INSPECT_ACTIONS = ('pwd', 'ls', 'find', 'du', 'head', 'tail', 'wc', 'stat', 'file')
DEFAULT_FIND_MAX_DEPTH = 3
DEFAULT_LS_MAX_ENTRIES = 200
DEFAULT_FIND_MAX_ENTRIES = 200
DEFAULT_DU_MAX_ENTRIES = 200
MAX_OUTPUT_LINES = 200
HEAD_TAIL_COMMANDS = {'head', 'tail'}
WC_ALLOWED_FLAGS = {'-l', '-c', '-w'}


class InspectPathTool(BaseTool):
    name = 'inspect_path'
    description = (
        'Safe read-only workspace inspection. Supports directory layout (pwd, ls, find, du) '
        'and lightweight file metadata (head, tail, wc, stat, file). '
        'No human approval required.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'action': {
                'type': 'string',
                'enum': list(ALLOWED_INSPECT_ACTIONS),
                'description': 'Action to run: pwd, ls, find, du for layout; head, tail, wc, stat, file for file metadata.',
            },
            'path': {
                'type': 'string',
                'description': 'Relative path inside the workspace. For head/tail/wc/stat/file this is the target file.',
            },
            'args': {
                'type': 'string',
                'description': (
                    'Extra arguments for head/tail/wc (e.g. "-n 20" for head/tail, "-l" for wc). '
                    'Ignored for other actions.'
                ),
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
            if action in HEAD_TAIL_COMMANDS:
                return self._run_head_tail(action, payload)
            if action == 'wc':
                return self._run_wc(payload)
            if action in ('stat', 'file'):
                return self._run_stat_file(action, payload)
            target = self._resolve_target(payload)
            if action == 'ls':
                return self._run_ls(target, payload)
            if action == 'find':
                return self._run_find(target, payload)
            return self._run_du(target, payload)
        except Exception as exc:
            return ToolExecutionResult(ok=False, content=str(exc))

    # --- Directory inspection actions ---

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

    # --- File metadata actions (merged from read_only_command) ---

    def _run_head_tail(self, action: str, payload: Mapping[str, Any]) -> ToolExecutionResult:
        path = self._resolve_file(payload)
        argv = [action]
        extra_args = self._parse_extra_args(payload)
        line_count = None
        idx = 0
        while idx < len(extra_args):
            arg = extra_args[idx]
            if arg == '-n':
                idx += 1
                if idx >= len(extra_args):
                    return ToolExecutionResult(ok=False, content='Expected a line count after -n.')
                try:
                    line_count = int(extra_args[idx])
                except ValueError:
                    return ToolExecutionResult(ok=False, content='Head/tail line count must be an integer.')
                if line_count <= 0:
                    return ToolExecutionResult(ok=False, content='Head/tail line count must be positive.')
                if line_count > MAX_OUTPUT_LINES:
                    return ToolExecutionResult(ok=False, content=f'Head/tail line count must be at most {MAX_OUTPUT_LINES}.')
                argv.extend(['-n', str(line_count)])
            elif arg.startswith('-'):
                return ToolExecutionResult(ok=False, content='Only the -n option is allowed for head/tail.')
            idx += 1
        argv.append(str(path))
        result = self.shell_runner.run_argv(argv, cwd=self.workspace_root)
        return self._command_result(result)

    def _run_wc(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        path = self._resolve_file(payload)
        argv = ['wc']
        extra_args = self._parse_extra_args(payload)
        for arg in extra_args:
            if arg.startswith('-'):
                if arg not in WC_ALLOWED_FLAGS:
                    return ToolExecutionResult(ok=False, content='Only -l, -w, or -c are allowed for wc.')
                argv.append(arg)
        argv.append(str(path))
        result = self.shell_runner.run_argv(argv, cwd=self.workspace_root)
        return self._command_result(result)

    def _run_stat_file(self, action: str, payload: Mapping[str, Any]) -> ToolExecutionResult:
        raw_path = str(payload.get('path') or '')
        if not raw_path:
            return ToolExecutionResult(ok=False, content=f'{action} requires a target path.')
        self.resolve_path(raw_path)  # validates path within workspace
        argv = [action, raw_path]
        result = self.shell_runner.run_argv(argv, cwd=self.workspace_root)
        return self._command_result(result)

    def _resolve_file(self, payload: Mapping[str, Any]) -> Path:
        raw_path = str(payload.get('path') or '')
        if not raw_path:
            raise ValueError('A target file path is required.')
        path = self.resolve_path(raw_path)
        if not path.exists():
            raise ValueError('Target path does not exist.')
        if not path.is_file():
            raise ValueError('Target path must be a file.')
        return path

    def _parse_extra_args(self, payload: Mapping[str, Any]) -> list[str]:
        raw = str(payload.get('args') or '')
        if not raw.strip():
            return []
        return shlex.split(raw)

    def _command_result(self, result: Any) -> ToolExecutionResult:
        output = {
            'command': result.command,
            'returncode': result.returncode,
            'stdout': result.stdout.rstrip('\n'),
            'stderr': result.stderr,
        }
        return ToolExecutionResult(ok=result.ok, content=json.dumps(output, ensure_ascii=False))

    # --- Shared helpers ---

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
