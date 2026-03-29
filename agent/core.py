from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.config import AgentConfig
from agent.llm import AnthropicLLM, BaseLLMClient, extract_text
from agent.policy import CommandPolicy
from agent.shell import ShellRunner
from agent.tools import BaseTool, ToolExecutionResult, build_tools


@dataclass
class AgentResponse:
    ok: bool
    command: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    message: str = ""
    should_exit: bool = False
    awaiting_confirmation: bool = False


@dataclass
class PendingApproval:
    base_messages: List[Dict[str, Any]]
    assistant_message: Dict[str, Any]
    tool_name: str
    tool_use_id: str
    tool_input: Dict[str, Any]


class Agent:
    """Minimal command-dispatch agent."""

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
        return AnthropicLLM(
            api_key=self.config.anthropic_api_key,
            model=self.config.anthropic_model,
            max_tokens=self.config.llm_max_tokens,
        )

    def handle(self, command: str) -> AgentResponse:
        normalized = command.strip()

        if self.pending_approval is not None:
            return self._handle_approval(normalized)

        if not normalized:
            return AgentResponse(
                ok=True,
                command=command,
                message="No command entered.",
            )

        if normalized in {"exit", "quit"}:
            return AgentResponse(
                ok=True,
                command=normalized,
                message="Session closed.",
                should_exit=True,
            )

        if normalized == "help":
            return AgentResponse(
                ok=True,
                command=normalized,
                message=(
                    "Built-in commands: help, exit, quit\n"
                    "If ANTHROPIC_API_KEY is configured, other input is sent to Claude with tool access.\n"
                    "Read-file tool calls execute immediately. Write-file and git tool calls require yes/no approval.\n"
                    "Without an API key, other input is executed as a shell command unless blocked by safety policy."
                ),
            )

        if self.llm is not None:
            return self._handle_llm_turn(normalized)

        decision = self.policy.evaluate(normalized)
        if not decision.allowed:
            return AgentResponse(
                ok=False,
                command=normalized,
                stderr=decision.reason,
                returncode=126,
            )

        result = self.shell_runner.run(normalized)
        return AgentResponse(
            ok=result.ok,
            command=result.command,
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    def _handle_llm_turn(self, user_input: str) -> AgentResponse:
        messages = self.history + [{"role": "user", "content": user_input}]
        return self._run_llm_loop(messages, user_input)

    def _handle_approval(self, user_input: str) -> AgentResponse:
        pending = self.pending_approval
        self.pending_approval = None

        approved = user_input.lower() in {"y", "yes"}
        tool = self.tools[pending.tool_name]

        if approved:
            result = tool.execute(pending.tool_input)
        else:
            result = ToolExecutionResult(ok=False, content="User denied tool execution.")

        tool_result_message = {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": pending.tool_use_id,
                    "content": result.content,
                    "is_error": not result.ok,
                }
            ],
        }
        messages = pending.base_messages + [pending.assistant_message, tool_result_message]
        return self._run_llm_loop(messages, user_input)

    def _run_llm_loop(self, messages: List[Dict[str, Any]], original_command: str) -> AgentResponse:
        if self.llm is None:
            return AgentResponse(
                ok=False,
                command=original_command,
                stderr="LLM is not configured.",
                returncode=1,
            )

        working_messages = list(messages)
        for _ in range(8):
            response = self.llm.generate(
                system_prompt=self._system_prompt(),
                messages=working_messages,
                tools=[tool.definition() for tool in self.tools.values()],
            )
            assistant_message = {"role": "assistant", "content": response.content}
            tool_uses = [
                block for block in response.content if block.get("type") == "tool_use"
            ]

            if tool_uses:
                tool_results = []
                for block in tool_uses:
                    tool_name = block["name"]
                    tool = self.tools[tool_name]
                    tool_input = dict(block.get("input") or {})
                    if tool.requires_approval:
                        self.pending_approval = PendingApproval(
                            base_messages=working_messages,
                            assistant_message=assistant_message,
                            tool_name=tool_name,
                            tool_use_id=block["id"],
                            tool_input=tool_input,
                        )
                        return AgentResponse(
                            ok=True,
                            command=original_command,
                            message=tool.approval_prompt(tool_input) + " [yes/no]",
                            awaiting_confirmation=True,
                        )

                    result = tool.execute(tool_input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": result.content,
                            "is_error": not result.ok,
                        }
                    )

                working_messages = working_messages + [
                    assistant_message,
                    {"role": "user", "content": tool_results},
                ]
                continue

            self.history = working_messages + [assistant_message]
            final_text = extract_text(response.content)
            return AgentResponse(
                ok=True,
                command=original_command,
                message=final_text or "No text response returned.",
            )

        return AgentResponse(
            ok=False,
            command=original_command,
            stderr="LLM tool loop exceeded the maximum number of steps.",
            returncode=1,
        )

    def _system_prompt(self) -> str:
        return (
            "You are a shell-oriented local coding agent. Use tools to inspect and modify the local "
            "workspace. Prefer reading files before making claims about file contents. Only request "
            "write_file when the user wants to create or edit local files. Only request git_run when "
            "you need repository information or git actions. Never request more than one approval-"
            "required tool call in the same response. If a write_file or git_run action is needed, "
            "request it and wait for approval. Summarize results clearly after tool execution."
        )
