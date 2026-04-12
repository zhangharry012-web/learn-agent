from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.config import AgentConfig
from agent.llm import BaseLLMClient, ToolResult, create_llm, extract_text
from agent.policy import CommandPolicy
from agent.runtime.messages import (
    build_assistant_message,
    build_system_prompt,
    build_tool_result_message,
)
from agent.runtime.types import AgentResponse, PendingApproval
from agent.shell import ShellRunner
from agent.tools import ToolExecutionResult, build_tools

MAX_LLM_TOOL_STEPS = 8


class Agent:
    def __init__(
        self,
        shell_runner: Optional[ShellRunner] = None,
        policy: Optional[CommandPolicy] = None,
        llm: Optional[BaseLLMClient] = None,
        config: Optional[AgentConfig] = None,
        workspace_root: Optional[Path] = None,
    ) -> None:
        self.config = config or AgentConfig()
        self.shell_runner = shell_runner or ShellRunner()
        self.policy = policy or CommandPolicy()
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.llm = llm or self._build_default_llm()
        self.tools = build_tools(
            workspace_root=self.workspace_root,
            shell_runner=self.shell_runner,
            enabled_tools=self.config.enabled_tools,
        )
        self.history: List[Dict[str, Any]] = []
        self.pending_approval: Optional[PendingApproval] = None

    def _build_default_llm(self) -> Optional[BaseLLMClient]:
        if not self.config.llm_enabled:
            return None
        return create_llm(
            provider=self.config.llm_provider,
            api_key=self.config.llm_api_key,
            model=self.config.llm_model,
            max_tokens=self.config.llm_max_tokens,
            base_url=self.config.llm_base_url,
        )

    def handle(self, command: str) -> AgentResponse:
        normalized = command.strip()
        if self.pending_approval is not None:
            return self._handle_approval(normalized)
        if not normalized:
            return AgentResponse(ok=True, command=command, message='No command entered.')
        if normalized in {'exit', 'quit'}:
            return AgentResponse(
                ok=True,
                command=normalized,
                message='Session closed.',
                should_exit=True,
            )
        if normalized == 'help':
            return AgentResponse(
                ok=True,
                command=normalized,
                message=(
                    'Built-in commands: help, exit, quit\n'
                    'If LLM credentials are configured, other input is sent to the configured provider with tool access.\n'
                    'Read-file tool calls execute immediately. Write-file and git tool calls require yes/no approval.\n'
                    'Without LLM credentials, other input is executed as a shell command unless blocked by safety policy.'
                ),
            )
        if self.llm is not None:
            return self._handle_llm_turn(normalized)
        return self._handle_shell_turn(normalized)

    def _handle_shell_turn(self, command: str) -> AgentResponse:
        decision = self.policy.evaluate(command)
        if not decision.allowed:
            return AgentResponse(
                ok=False,
                command=command,
                stderr=decision.reason,
                returncode=126,
            )
        result = self.shell_runner.run(command)
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
        tool = self.tools[pending.tool_name]
        result = (
            tool.execute(pending.tool_input)
            if user_input.lower() in {'y', 'yes'}
            else ToolExecutionResult(ok=False, content='User denied tool execution.')
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
        for _ in range(MAX_LLM_TOOL_STEPS):
            response = self.llm.generate(
                system_prompt=build_system_prompt(),
                messages=working_messages,
                tools=[tool.definition() for tool in self.tools.values()],
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
                        return AgentResponse(
                            ok=True,
                            command=original_command,
                            message=tool.approval_prompt(tool_input) + ' [yes/no]',
                            awaiting_confirmation=True,
                        )
                    result = tool.execute(tool_input)
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
        return AgentResponse(
            ok=False,
            command=original_command,
            stderr='LLM tool loop exceeded the maximum number of steps.',
            returncode=1,
        )
