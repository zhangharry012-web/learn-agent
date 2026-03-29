from __future__ import annotations

from dataclasses import dataclass

from agent.policy import CommandPolicy
from agent.shell import ShellRunner


@dataclass
class AgentResponse:
    ok: bool
    command: str
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    message: str = ""
    should_exit: bool = False


class Agent:
    """Minimal command-dispatch agent."""

    def __init__(
        self,
        shell_runner: ShellRunner | None = None,
        policy: CommandPolicy | None = None,
    ) -> None:
        self.shell_runner = shell_runner or ShellRunner()
        self.policy = policy or CommandPolicy()

    def handle(self, command: str) -> AgentResponse:
        normalized = command.strip()

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
                    "Other input is executed as a shell command unless blocked by safety policy."
                ),
            )

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
