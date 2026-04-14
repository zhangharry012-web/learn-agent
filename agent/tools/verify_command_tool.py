from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from agent.config import AgentConfig
from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.types import ToolExecutionResult
from agent.verify import (
    VerifyCommandRejected,
    VerifyPolicyError,
    VerifyPolicyMismatch,
    ensure_no_shell_tokens,
    extract_path_args,
    json_result,
    relative_path,
    resolve_cwd,
    select_rule,
    timeout_for_rule,
    validate_language_command,
)


class VerifyCommandTool(BaseTool):
    name = 'verify_command'
    description = (
        'Execute a narrow set of verification, test, lint, and build commands inside the current workspace without human approval. '
        'Use this tool after modifying code when the goal is to validate the change safely. '
        'Do not use it for arbitrary shell commands, dependency installation, publishing, deployment, network access, or custom script execution outside the approved verification subset.'
    )
    input_schema = {
        'type': 'object',
        'properties': {
            'argv': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': 'Structured argv for a safe verification command.',
            },
            'cwd': {
                'type': 'string',
                'description': 'Optional relative working directory inside the workspace. Defaults to the workspace root.',
            },
            'reason': {
                'type': 'string',
                'description': 'Optional short reason for running the verification command.',
            },
        },
        'required': ['argv'],
    }

    def __init__(
        self,
        workspace_root: Path,
        shell_runner: ShellRunner,
        config: AgentConfig,
    ) -> None:
        super().__init__(workspace_root)
        self.shell_runner = shell_runner
        self.config = config

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            argv = self._parse_argv(payload)
            ensure_no_shell_tokens(argv)
            validate_language_command(argv)
            cwd = resolve_cwd(self.workspace_root, str(payload.get('cwd') or '.'))
            relative_cwd = relative_path(self.workspace_root, cwd)
            path_args = extract_path_args(argv, self.workspace_root)
            rule = select_rule(argv, relative_cwd, path_args, self.workspace_root, self.config)
            result = self.shell_runner.run_argv(argv, cwd=cwd, timeout=timeout_for_rule(rule, self.config))
            return ToolExecutionResult(ok=result.ok, content=json_result(result, argv, relative_cwd, rule))
        except (VerifyCommandRejected, VerifyPolicyMismatch, VerifyPolicyError, ValueError) as exc:
            return ToolExecutionResult(ok=False, content=str(exc))

    def _parse_argv(self, payload: Mapping[str, Any]) -> list[str]:
        raw_argv = payload.get('argv')
        if not isinstance(raw_argv, list) or not raw_argv:
            raise VerifyCommandRejected('verify_command argv must be a non-empty string array.')
        argv = [str(item).strip() for item in raw_argv]
        if any(not item for item in argv):
            raise VerifyCommandRejected('verify_command argv entries must not be empty.')
        return argv
