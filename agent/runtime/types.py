from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class AgentResponse:
    ok: bool
    command: str
    stdout: str = ''
    stderr: str = ''
    returncode: int = 0
    message: str = ''
    should_exit: bool = False
    awaiting_confirmation: bool = False
    session_summary: Optional[Dict[str, Any]] = None


@dataclass
class PendingApproval:
    base_messages: List[Dict[str, Any]]
    assistant_message: Dict[str, Any]
    tool_name: str
    tool_use_id: str
    tool_input: Dict[str, Any]
