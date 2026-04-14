from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Optional

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

VERIFY_EXECUTION_REQUESTED = 'verify.execution.requested'
VERIFY_EXECUTION_COMPLETED = 'verify.execution.completed'
VERIFY_EXECUTION_REJECTED = 'verify.execution.rejected'

VerifyEventLogger = Callable[[str, Mapping[str, Any]], None]


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
        event_logger: Optional[VerifyEventLogger] = None,
    ) -> None:
        super().__init__(workspace_root)
        self.shell_runner = shell_runner
        self.config = config
        self.event_logger = event_logger

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        argv = []
        relative_cwd = '.'
        reason = str(payload.get('reason') or '')
        try:
            argv = self._parse_argv(payload)
            cwd = resolve_cwd(self.workspace_root, str(payload.get('cwd') or '.'))
            relative_cwd = relative_path(self.workspace_root, cwd)
            self._emit(
                VERIFY_EXECUTION_REQUESTED,
                {
                    'argv': argv,
                    'cwd': relative_cwd,
                    'reason': reason,
                },
            )
            ensure_no_shell_tokens(argv)
            validate_language_command(argv)
            path_args = extract_path_args(argv, self.workspace_root)
            rule = select_rule(argv, relative_cwd, path_args, self.workspace_root, self.config)
            timeout_sec = timeout_for_rule(rule, self.config)
            result = self.shell_runner.run_argv(argv, cwd=cwd, timeout=timeout_sec)
            content = json_result(result, argv, relative_cwd, rule)
            self._emit(
                VERIFY_EXECUTION_COMPLETED,
                {
                    'argv': argv,
                    'cwd': relative_cwd,
                    'reason': reason,
                    'rule_id': rule.rule_id,
                    'timeout_sec': timeout_sec,
                    'returncode': result.returncode,
                    'ok': result.ok,
                },
            )
            return ToolExecutionResult(ok=result.ok, content=content)
        except (VerifyCommandRejected, VerifyPolicyMismatch, VerifyPolicyError, ValueError) as exc:
            self._emit(
                VERIFY_EXECUTION_REJECTED,
                {
                    'argv': argv,
                    'cwd': relative_cwd,
                    'reason': reason,
                    'error': str(exc),
                },
            )
            return ToolExecutionResult(ok=False, content=str(exc))

    def _emit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if self.event_logger is None:
            return
        self.event_logger(event_type, payload)

    def _parse_argv(self, payload: Mapping[str, Any]) -> list[str]:
        raw_argv = payload.get('argv')
        if not isinstance(raw_argv, list) or not raw_argv:
            raise VerifyCommandRejected('verify_command argv must be a non-empty string array.')
        argv = [str(item).strip() for item in raw_argv]
        if any(not item for item in argv):
            raise VerifyCommandRejected('verify_command argv entries must not be empty.')
        return argv
