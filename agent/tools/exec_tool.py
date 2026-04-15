from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.types import ToolExecutionResult


class ExecTool(BaseTool):
    name = 'exec'
    description = (
        'Execute an arbitrary shell command inside the current workspace. '
        'Requires human approval before execution.'
    )
    requires_approval = True
    input_schema = {
        'type': 'object',
        'properties': {
            'command': {
                'type': 'string',
                'description': (
                    'Shell command to execute inside the workspace root. '
                    'Use only when no narrower tool applies.'
                ),
            }
        },
        'required': ['command'],
    }

    def __init__(self, workspace_root: Path, shell_runner: ShellRunner) -> None:
        super().__init__(workspace_root)
        self.shell_runner = shell_runner

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        command = str(payload['command'])
        result = self.shell_runner.run(command, cwd=self.workspace_root)
        output = {
            'command': result.command,
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
        }
        return ToolExecutionResult(ok=result.ok, content=json.dumps(output, ensure_ascii=False))

    def approval_prompt(self, payload: Mapping[str, Any]) -> str:
        return f"Approve shell command? {payload.get('command', '')}".strip()
