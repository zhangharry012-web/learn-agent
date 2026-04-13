from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Mapping

from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.types import ToolExecutionResult


READ_ONLY_GIT_SUBCOMMANDS = {'status', 'diff', 'log', 'show'}
DISALLOWED_GIT_FLAGS = {'--cached', '--staged'}


class GitInspectTool(BaseTool):
    name = 'git_inspect'
    description = (
        'Run a small set of read-only git inspection commands inside the current repository without '
        'human approval. Supports only status, diff, log, and show arguments.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'args': {
                'type': 'string',
                'description': "Read-only git arguments excluding the leading 'git', for example 'status --short'.",
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
        except ValueError as exc:
            return ToolExecutionResult(ok=False, content=str(exc))
        validation_error = self._validate_args(args)
        if validation_error is not None:
            return ToolExecutionResult(ok=False, content=validation_error)
        result = self.shell_runner.run_argv(['git'] + args, cwd=self.workspace_root)
        output = {
            'command': result.command,
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
        }
        return ToolExecutionResult(ok=result.ok, content=json.dumps(output, ensure_ascii=False))

    def _validate_args(self, args: list) -> str | None:
        if not args:
            return 'Git inspect args must not be empty.'
        subcommand = args[0]
        if subcommand not in READ_ONLY_GIT_SUBCOMMANDS:
            return 'Only read-only git inspect commands are allowed.'
        for arg in args[1:]:
            if arg in DISALLOWED_GIT_FLAGS:
                return 'This git inspect flag is not allowed.'
            if arg.startswith('-c') or arg == '--config-env':
                return 'Inline git config overrides are not allowed.'
        return None
