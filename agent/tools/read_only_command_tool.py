from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Mapping

from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.types import ToolExecutionResult


ALLOWED_READ_ONLY_COMMANDS = {'head', 'tail', 'wc', 'stat', 'file'}
MAX_OUTPUT_LINES = 200
HEAD_TAIL_COMMANDS = {'head', 'tail'}
WC_ALLOWED_FLAGS = {'-l', '-c', '-w'}
SHELL_COMPOSITION_TOKENS = {'|', '&&', ';'}


class ReadOnlyCommandTool(BaseTool):
    name = 'read_only_command'
    description = (
        'Run a small read-only command subset inside the workspace without human approval. '
        'Only head, tail, wc, stat, and file are allowed — nothing else. '
        'Do not use it for full file contents because read_file is the correct tool. '
        'Do not use it for workspace layout (ls/find/du) because inspect_path is the correct tool. '
        'Do not use it for build, test, or lint commands because verify_command is the correct tool.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'args': {
                'type': 'string',
                'description': (
                    "Read-only command arguments excluding the command prefix itself, "
                    "for example 'head -n 20 README.md' or 'wc -l agent/tools/file_tools.py'."
                ),
            }
        },
        'required': ['args'],
    }

    def __init__(self, workspace_root: Path, shell_runner: ShellRunner) -> None:
        super().__init__(workspace_root)
        self.shell_runner = shell_runner

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            args = shlex.split(str(payload['args']))
            validation_error = self._validate_args(args)
            if validation_error is not None:
                return ToolExecutionResult(ok=False, content=validation_error)
            result = self.shell_runner.run_argv(args, cwd=self.workspace_root)
            output = {
                'command': result.command,
                'returncode': result.returncode,
                'stdout': result.stdout.rstrip('\n'),
                'stderr': result.stderr,
            }
            return ToolExecutionResult(ok=result.ok, content=json.dumps(output, ensure_ascii=False))
        except Exception as exc:
            return ToolExecutionResult(ok=False, content=str(exc))

    def _validate_args(self, args: list[str]) -> str | None:
        if not args:
            return 'Read-only command args must not be empty.'
        command = args[0]
        if command == 'cat':
            return 'Use read_file for direct file contents instead of cat.'
        if command not in ALLOWED_READ_ONLY_COMMANDS:
            return 'Only a small read-only command subset is allowed.'
        if any(token in SHELL_COMPOSITION_TOKENS for token in args):
            return 'Shell composition tokens are not allowed.'
        if command in HEAD_TAIL_COMMANDS:
            return self._validate_head_tail(args)
        if command == 'wc':
            return self._validate_wc(args)
        return self._validate_single_path_command(args, command)

    def _validate_head_tail(self, args: list[str]) -> str | None:
        paths: list[str] = []
        index = 1
        while index < len(args):
            arg = args[index]
            if arg == '-n':
                index += 1
                if index >= len(args):
                    return 'Expected a line count after -n.'
                try:
                    count = int(args[index])
                except ValueError:
                    return 'Head/tail line count must be an integer.'
                if count <= 0:
                    return 'Head/tail line count must be positive.'
                if count > MAX_OUTPUT_LINES:
                    return f'Head/tail line count must be at most {MAX_OUTPUT_LINES}.'
            elif arg.startswith('-'):
                return 'Only the -n option is allowed for head/tail.'
            else:
                paths.append(arg)
            index += 1
        if len(paths) != 1:
            return 'Head/tail require exactly one target file.'
        return self._validate_existing_file(paths[0])

    def _validate_wc(self, args: list[str]) -> str | None:
        paths: list[str] = []
        for arg in args[1:]:
            if arg.startswith('-'):
                if arg not in WC_ALLOWED_FLAGS:
                    return 'Only -l, -w, or -c are allowed for wc.'
            else:
                paths.append(arg)
        if len(paths) != 1:
            return 'wc requires exactly one target file.'
        return self._validate_existing_file(paths[0])

    def _validate_single_path_command(self, args: list[str], command: str) -> str | None:
        if len(args) != 2:
            return f'{command} requires exactly one target path and no extra flags.'
        self.resolve_path(args[1])
        return None

    def _validate_existing_file(self, raw_path: str) -> str | None:
        path = self.resolve_path(raw_path)
        if not path.exists():
            return 'Target path does not exist.'
        if not path.is_file():
            return 'Target path must be a file.'
        return None
