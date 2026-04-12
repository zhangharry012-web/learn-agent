from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolExecutionResult:
    ok: bool
    content: str
