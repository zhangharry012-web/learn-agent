from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""


class CommandPolicy:
    """Applies a minimal denylist for obviously destructive shell commands."""

    BLOCKED_BASE_COMMANDS = {
        "dd",
        "fdisk",
        "format",
        "halt",
        "mkfs",
        "poweroff",
        "reboot",
        "rm",
        "shutdown",
        "sudo",
    }

    BLOCKED_PATTERNS = {
        "rm -rf /",
        "rm -fr /",
        ":(){:|:&};:",
    }

    def evaluate(self, command: str) -> PolicyDecision:
        normalized = command.strip()
        if not normalized:
            return PolicyDecision(allowed=True)

        lowered = normalized.lower()
        for pattern in self.BLOCKED_PATTERNS:
            if pattern in lowered:
                return PolicyDecision(
                    allowed=False,
                    reason="Command blocked by safety policy: destructive pattern detected.",
                )

        try:
            parts = shlex.split(normalized)
        except ValueError:
            return PolicyDecision(
                allowed=False,
                reason="Command blocked by safety policy: unable to parse shell input safely.",
            )

        if not parts:
            return PolicyDecision(allowed=True)

        base_command = parts[0].lower()
        if base_command in self.BLOCKED_BASE_COMMANDS:
            return PolicyDecision(
                allowed=False,
                reason=f"Command blocked by safety policy: '{base_command}' is not allowed.",
            )

        return PolicyDecision(allowed=True)
