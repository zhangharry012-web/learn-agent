from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.config import AgentConfig
from agent.llm import BaseLLMClient, ToolResult, create_llm, extract_text
from agent.llm.types import LLMToolCallFormatError
from agent.policy import CommandPolicy
from agent.runtime.events import (
    COMMAND_BLOCKED,
    COMMAND_COMPLETED,
    COMMAND_RECEIVED,
    LLM_LOOP_LIMIT_EXCEEDED,
    LLM_PANIC,
    LLM_RESPONSE_COMPLETED,
    SESSION_SUMMARY,
    SHELL_EXECUTION_COMPLETED,
    TOOL_APPROVAL_COMPLETED,
    TOOL_APPROVAL_REQUESTED,
    TOOL_EXECUTION_COMPLETED,
)
from agent.runtime.messages import (
    build_assistant_message,
    build_system_prompt,
    build_tool_result_message,
)
from agent.runtime.observability import ObservabilityLogger
from agent.runtime.types import AgentResponse, PendingApproval
from agent.shell import ShellRunner
from agent.tools import ToolExecutionResult, build_tools

MAX_LLM_TOOL_STEPS = 8
LLM_PANIC_RETRY_MESSAGE = 'LLM 调用发生内部错误，已记录异常日志。请发送错误并重新尝试。'


class Agent:
    def __init__(
        self,
        shell_runner: Optional[ShellRunner] = None,
        policy: Optional[CommandPolicy] = None,
        llm: Optional[BaseLLMClient] = None,
        config: Optional[AgentConfig] = None,
        workspace_root: Optional[Path] = None,
        observability_logger: Optional[ObservabilityLogger] = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.shell_runner = shell_runner or ShellRunner()
        self.policy = policy or CommandPolicy()
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.current_llm_max_tokens = self.config.llm_max_tokens
        self.llm = llm or self._build_default_llm(self.current_llm_max_tokens)
        self.tools = build_tools(
            workspace_root=self.workspace_root,
            shell_runner=self.shell_runner,
            enabled_tools=self.config.enabled_tools,
        )
        self.history: List[Dict[str, Any]] = []
        self.pending_approval: Optional[PendingApproval] = None
        self.session_id = uuid.uuid4().hex
        self.observability = observability_logger or ObservabilityLogger(
            log_dir=self.workspace_root / self.config.observability_log_dir,
            enabled=self.config.observability_enabled,
            preview_chars=self.config.observability_preview_chars,
            retention_hours=self.config.observability_retention_hours,
        )
        self.exception_log_dir = self.workspace_root / self.config.exception_log_dir
        self._session_totals: Dict[str, Any] = {
            'token_usage': {
                'input_tokens': 0,
                'output_tokens': 0,
                'total_tokens': 0,
            },
            'llm_call_count': 0,
            'tool_call_count': 0,
            'tool_call_breakdown': {},
            'tool_success_count': 0,
            'tool_failure_count': 0,
            'tool_outcome_breakdown': {},
            'shell_command_count': 0,
            'command_count': 0,
            'summary_emitted': False,
        }

    def _build_default_llm(self, max_tokens: Optional[int] = None) -> Optional[BaseLLMClient]:
        if not self.config.llm_enabled:
            return None
        return create_llm(
            provider=self.config.llm_provider,
            api_key=self.config.llm_api_key,
            model=self.config.llm_model,
            max_tokens=max_tokens if max_tokens is not None else self.current_llm_max_tokens,
            base_url=self.config.llm_base_url,
        )

    def _upgrade_llm_max_tokens(self) -> bool:
        fallback_max_tokens = self.config.llm_fallback_max_tokens
        if fallback_max_tokens <= self.current_llm_max_tokens:
            return False
        self.current_llm_max_tokens = fallback_max_tokens
        self.llm = self._build_default_llm(self.current_llm_max_tokens)
        return self.llm is not None

    def handle(self, command: str) -> AgentResponse:
        started_at = time.perf_counter()
        normalized = command.strip()
        mode = 'input'
        self._session_totals['command_count'] += 1
        self.observability.log_event(
            COMMAND_RECEIVED,
            self.session_id,
            {'command': command, 'normalized_command': normalized},
        )
        if self.pending_approval is not None:
            mode = 'approval_response'
            response = self._handle_approval(normalized)
        elif not normalized:
            mode = 'built_in'
            response = AgentResponse(ok=True, command=command, message='No command entered.')
        elif normalized in {'exit', 'quit'}:
            mode = 'built_in'
            response = AgentResponse(
                ok=True,
                command=normalized,
                message='Session closed.',
                should_exit=True,
            )
        elif normalized == 'help':
            mode = 'built_in'
            response = AgentResponse(
                ok=True,
                command=normalized,
                message=(
                    'Built-in commands: help, exit, quit\n'
                    'If LLM credentials are configured, other input is sent to the configured provider with tool access.\n'
                    'Read-file tool calls execute immediately. Write-file, edit-file, exec, and git tool calls require yes/no approval.\n'
                    'Without LLM credentials, other input is executed as a shell command unless blocked by safety policy.'
                ),
            )
        elif self.llm is not None:
            mode = 'llm'
            response = self._handle_llm_turn(normalized)
        else:
            mode = 'shell_fallback'
            response = self._handle_shell_turn(normalized)
        self.observability.log_event(
            COMMAND_COMPLETED,
            self.session_id,
            {
                'command': command,
                'mode': mode,
                'ok': response.ok,
                'awaiting_confirmation': response.awaiting_confirmation,
                'returncode': response.returncode,
                'duration_ms': round((time.perf_counter() - started_at) * 1000, 3),
                'message': response.message,
                'stdout': response.stdout,
                'stderr': response.stderr,
            },
        )
        if response.should_exit:
            response.session_summary = self._log_session_summary(command=normalized, trigger='session_exit')
        return response

    def _handle_shell_turn(self, command: str) -> AgentResponse:
        started_at = time.perf_counter()
        decision = self.policy.evaluate(command)
        if not decision.allowed:
            self.observability.log_event(
                COMMAND_BLOCKED,
                self.session_id,
                {
                    'command': command,
                    'reason': decision.reason,
                    'duration_ms': round((time.perf_counter() - started_at) * 1000, 3),
                },
            )
            return AgentResponse(
                ok=False,
                command=command,
                stderr=decision.reason,
                returncode=126,
            )
        result = self.shell_runner.run(command)
        self._session_totals['shell_command_count'] += 1
        self.observability.log_event(
            SHELL_EXECUTION_COMPLETED,
            self.session_id,
            {
                'command': result.command,
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'duration_ms': round((time.perf_counter() - started_at) * 1000, 3),
            },
        )
        return AgentResponse(
            ok=result.ok,
            command=result.command,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    def _handle_llm_turn(self, user_input: str) -> AgentResponse:
        messages = self.history + [{'role': 'user', 'content': user_input}]
        return self._run_llm_loop(messages, user_input)

    def _handle_approval(self, user_input: str) -> AgentResponse:
        pending = self.pending_approval
        if pending is None:
            return AgentResponse(ok=False, command=user_input, stderr='No pending approval.', returncode=1)
        self.pending_approval = None
        approved = user_input.lower() in {'y', 'yes'}
        self.observability.log_event(
            TOOL_APPROVAL_COMPLETED,
            self.session_id,
            {
                'tool_name': pending.tool_name,
                'approved': approved,
                'tool_input': pending.tool_input,
            },
        )
        tool = self.tools[pending.tool_name]
        started_at = time.perf_counter()
        result = (
            tool.execute(pending.tool_input)
            if approved
            else ToolExecutionResult(ok=False, content='User denied tool execution.')
        )
        self._record_tool_call(pending.tool_name, result.ok)
        self.observability.log_event(
            TOOL_EXECUTION_COMPLETED,
            self.session_id,
            {
                'tool_name': pending.tool_name,
                'approved': approved,
                'ok': result.ok,
                'tool_input': pending.tool_input,
                'result': result.content,
                'duration_ms': round((time.perf_counter() - started_at) * 1000, 3),
            },
        )
        tool_result_message = build_tool_result_message(
            [
                ToolResult(
                    tool_call_id=pending.tool_use_id,
                    content=result.content,
                    is_error=not result.ok,
                )
            ]
        )
        messages = pending.base_messages + [pending.assistant_message, tool_result_message]
        return self._run_llm_loop(messages, user_input)

    def _run_llm_loop(self, messages: List[Dict[str, Any]], original_command: str) -> AgentResponse:
        if self.llm is None:
            return AgentResponse(
                ok=False,
                command=original_command,
                stderr='LLM is not configured.',
                returncode=1,
            )
        working_messages = list(messages)
        format_retry_used = False
        for step in range(MAX_LLM_TOOL_STEPS):
            started_at = time.perf_counter()
            try:
                response = self.llm.generate(
                    system_prompt=build_system_prompt(),
                    messages=working_messages,
                    tools=[tool.definition() for tool in self.tools.values()],
                )
            except LLMToolCallFormatError as exc:
                if not format_retry_used and self._upgrade_llm_max_tokens():
                    format_retry_used = True
                    continue
                return self._handle_llm_panic(exc, original_command, step + 1, working_messages)
            except Exception as exc:
                return self._handle_llm_panic(exc, original_command, step + 1, working_messages)
            self._record_llm_usage(response.usage)
            self.observability.log_event(
                LLM_RESPONSE_COMPLETED,
                self.session_id,
                {
                    'step': step + 1,
                    'provider': self.config.llm_provider,
                    'model': self.config.llm_model,
                    'max_tokens': self.current_llm_max_tokens,
                    'message_count': len(working_messages),
                    'tool_count': len(self.tools),
                    'duration_ms': round((time.perf_counter() - started_at) * 1000, 3),
                    'stop_reason': response.stop_reason,
                    'text': response.text,
                    'tool_calls': [
                        {
                            'id': tool_call.id,
                            'name': tool_call.name,
                            'arguments': tool_call.arguments,
                        }
                        for tool_call in response.tool_calls
                    ],
                    'usage': None
                    if response.usage is None
                    else {
                        'input_tokens': response.usage.input_tokens,
                        'output_tokens': response.usage.output_tokens,
                        'total_tokens': response.usage.total_tokens,
                    },
                },
            )
            assistant_message = build_assistant_message(response.text, response.tool_calls)
            if response.tool_calls:
                tool_results: List[ToolResult] = []
                for tool_call in response.tool_calls:
                    tool = self.tools[tool_call.name]
                    tool_input = dict(tool_call.arguments)
                    if tool.requires_approval:
                        self.pending_approval = PendingApproval(
                            base_messages=working_messages,
                            assistant_message=assistant_message,
                            tool_name=tool_call.name,
                            tool_use_id=tool_call.id,
                            tool_input=tool_input,
                        )
                        self.observability.log_event(
                            TOOL_APPROVAL_REQUESTED,
                            self.session_id,
                            {
                                'tool_name': tool_call.name,
                                'tool_input': tool_input,
                                'tool_use_id': tool_call.id,
                            },
                        )
                        return AgentResponse(
                            ok=True,
                            command=original_command,
                            message=tool.approval_prompt(tool_input) + ' [yes/no]',
                            awaiting_confirmation=True,
                        )
                    tool_started_at = time.perf_counter()
                    result = tool.execute(tool_input)
                    self._record_tool_call(tool_call.name, result.ok)
                    self.observability.log_event(
                        TOOL_EXECUTION_COMPLETED,
                        self.session_id,
                        {
                            'tool_name': tool_call.name,
                            'approved': True,
                            'ok': result.ok,
                            'tool_input': tool_input,
                            'result': result.content,
                            'duration_ms': round((time.perf_counter() - tool_started_at) * 1000, 3),
                        },
                    )
                    tool_results.append(
                        ToolResult(
                            tool_call_id=tool_call.id,
                            content=result.content,
                            is_error=not result.ok,
                        )
                    )
                working_messages = working_messages + [
                    assistant_message,
                    build_tool_result_message(tool_results),
                ]
                continue
            self.history = working_messages + [assistant_message]
            final_text = extract_text(response)
            return AgentResponse(
                ok=True,
                command=original_command,
                message=final_text or 'No text response returned.',
            )
        self.observability.log_event(
            LLM_LOOP_LIMIT_EXCEEDED,
            self.session_id,
            {
                'command': original_command,
                'max_steps': MAX_LLM_TOOL_STEPS,
            },
        )
        return AgentResponse(
            ok=False,
            command=original_command,
            stderr='LLM exceeded the maximum tool interaction limit.',
            returncode=1,
        )

    def _handle_llm_panic(
        self,
        error: Exception,
        original_command: str,
        step: int,
        messages: List[Dict[str, Any]],
    ) -> AgentResponse:
        log_path = self.observability.log_exception(
            self.session_id,
            error,
            {
                'command': original_command,
                'step': step,
                'message_count': len(messages),
            },
            self.exception_log_dir,
        )
        self.observability.log_event(
            LLM_PANIC,
            self.session_id,
            {
                'command': original_command,
                'step': step,
                'error_type': error.__class__.__name__,
                'error_message': str(error),
                'exception_log_path': None if log_path is None else str(log_path),
            },
        )
        return AgentResponse(
            ok=False,
            command=original_command,
            stderr=LLM_PANIC_RETRY_MESSAGE,
            returncode=1,
        )

    def _record_llm_usage(self, usage: Any) -> None:
        self._session_totals['llm_call_count'] += 1
        if usage is None:
            return
        tokens = self._session_totals['token_usage']
        tokens['input_tokens'] += getattr(usage, 'input_tokens', 0) or 0
        tokens['output_tokens'] += getattr(usage, 'output_tokens', 0) or 0
        tokens['total_tokens'] += getattr(usage, 'total_tokens', 0) or 0

    def _record_tool_call(self, tool_name: str, ok: bool) -> None:
        self._session_totals['tool_call_count'] += 1
        breakdown = self._session_totals['tool_call_breakdown']
        breakdown[tool_name] = breakdown.get(tool_name, 0) + 1
        if ok:
            self._session_totals['tool_success_count'] += 1
        else:
            self._session_totals['tool_failure_count'] += 1
        outcome_breakdown = self._session_totals['tool_outcome_breakdown']
        stats = outcome_breakdown.setdefault(tool_name, {'ok': 0, 'error': 0})
        if ok:
            stats['ok'] += 1
        else:
            stats['error'] += 1

    def _build_session_summary(self, *, command: str, trigger: str) -> Dict[str, Any]:
        outcome_breakdown = {
            name: {'ok': stats['ok'], 'error': stats['error']}
            for name, stats in sorted(self._session_totals['tool_outcome_breakdown'].items())
        }
        return {
            'trigger': trigger,
            'command': command,
            'command_count': self._session_totals['command_count'],
            'llm_call_count': self._session_totals['llm_call_count'],
            'tool_call_count': self._session_totals['tool_call_count'],
            'tool_call_breakdown': dict(sorted(self._session_totals['tool_call_breakdown'].items())),
            'tool_success_count': self._session_totals['tool_success_count'],
            'tool_failure_count': self._session_totals['tool_failure_count'],
            'tool_outcome_breakdown': outcome_breakdown,
            'shell_command_count': self._session_totals['shell_command_count'],
            'token_usage': dict(self._session_totals['token_usage']),
        }

    def _log_session_summary(self, *, command: str, trigger: str) -> Dict[str, Any]:
        summary = self._build_session_summary(command=command, trigger=trigger)
        if self._session_totals['summary_emitted']:
            return summary
        self._session_totals['summary_emitted'] = True
        self.observability.log_event(SESSION_SUMMARY, self.session_id, summary)
        return summary
