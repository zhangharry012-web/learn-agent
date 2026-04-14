from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from agent.tools.types import ToolExecutionResult


class BaseTool:
    name = ''
    description = ''
    input_schema: Dict[str, Any] = {}
    requires_approval = False

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def definition(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'description': self.description,
            'input_schema': self.input_schema,
        }

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        raise NotImplementedError

    def approval_prompt(self, payload: Mapping[str, Any]) -> str:
        return f"Approve tool '{self.name}' with input: {json.dumps(dict(payload), ensure_ascii=False)}"

    def resolve_path(self, raw_path: str) -> Path:
        candidate = (self.workspace_root / raw_path).resolve()
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError('Path escapes the workspace root.') from exc
        return candidate
