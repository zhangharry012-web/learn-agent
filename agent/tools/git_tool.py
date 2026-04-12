from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any, Mapping

from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.types import ToolExecutionResult


class GitTool(BaseTool):
    name = 'git_run'
    description = (
        'Run a git command inside the current repository using the local shell runner. Use this '
        'tool for git status, diff, add, commit, branch, and other repository operations. '
        'This tool always requires human approval before execution. Provide only git arguments, '
        "for example 'status --short' or 'diff -- README.md'."
    )
    requires_approval = True
    input_schema = {
        'type': 'object',
        'properties': {
            'args': {
                'type': 'string',
                'description': "Git arguments excluding the leading 'git'.",
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

        result = self.shell_runner.run_argv(['git'] + args, cwd=self.workspace_root)
        output = {
            'command': result.command,
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
        }
        return ToolExecutionResult(ok=result.ok, content=json.dumps(output, ensure_ascii=False))

    def approval_prompt(self, payload: Mapping[str, Any]) -> str:
        return f"Approve git command? git {payload.get('args', '')}".strip()
