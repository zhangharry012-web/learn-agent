from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from agent.shell import ShellRunner


@dataclass
class ToolExecutionResult:
    ok: bool
    content: str


class BaseTool:
    name = ""
    description = ""
    input_schema: Dict[str, Any] = {}
    requires_approval = False

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def definition(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        raise NotImplementedError

    def approval_prompt(self, payload: Mapping[str, Any]) -> str:
        return f"Approve tool '{self.name}' with input: {json.dumps(dict(payload), ensure_ascii=False)}"

    def resolve_path(self, raw_path: str) -> Path:
        candidate = (self.workspace_root / raw_path).resolve()
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError:
            raise ValueError("Path escapes the workspace root.")
        return candidate


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read a local text file from the current workspace. Use this tool whenever you need "
        "to inspect project files before answering or taking action. This tool is read-only "
        "and does not require human approval. Prefer relative paths rooted in the project."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to a UTF-8 text file in the workspace.",
            },
            "start_line": {
                "type": "integer",
                "description": "Optional 1-based starting line number.",
            },
            "end_line": {
                "type": "integer",
                "description": "Optional 1-based ending line number, inclusive.",
            },
        },
        "required": ["path"],
    }

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            path = self.resolve_path(str(payload["path"]))
            content = path.read_text(encoding="utf-8")
            lines = content.splitlines()
            start_line = int(payload.get("start_line") or 1)
            end_line = int(payload.get("end_line") or len(lines))
            selected = lines[start_line - 1 : end_line]
            result = {
                "path": str(path.relative_to(self.workspace_root)),
                "start_line": start_line,
                "end_line": end_line,
                "content": "\n".join(selected),
            }
            return ToolExecutionResult(ok=True, content=json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            return ToolExecutionResult(ok=False, content=str(exc))


class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "Write text to a local file in the current workspace. Use this tool only when the user "
        "explicitly wants file content created or modified. This tool always requires human "
        "approval before execution. The mode can be overwrite or append."
    )
    requires_approval = True
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "Full text content to write.",
            },
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "description": "Whether to replace the file or append to it.",
            },
        },
        "required": ["path", "content", "mode"],
    }

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            path = self.resolve_path(str(payload["path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            mode = str(payload["mode"])
            content = str(payload["content"])
            if mode == "overwrite":
                path.write_text(content, encoding="utf-8")
            elif mode == "append":
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(content)
            else:
                return ToolExecutionResult(ok=False, content="Unsupported write mode.")

            result = {
                "path": str(path.relative_to(self.workspace_root)),
                "mode": mode,
                "bytes_written": len(content.encode("utf-8")),
            }
            return ToolExecutionResult(ok=True, content=json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            return ToolExecutionResult(ok=False, content=str(exc))

    def approval_prompt(self, payload: Mapping[str, Any]) -> str:
        return (
            "Approve file write? "
            f"path={payload.get('path')} mode={payload.get('mode')} "
            f"bytes={len(str(payload.get('content', '')).encode('utf-8'))}"
        )


class GitTool(BaseTool):
    name = "git_run"
    description = (
        "Run a git command inside the current repository using the local shell runner. Use this "
        "tool for git status, diff, add, commit, branch, and other repository operations. "
        "This tool always requires human approval before execution. Provide only git arguments, "
        "for example 'status --short' or 'diff -- README.md'."
    )
    requires_approval = True
    input_schema = {
        "type": "object",
        "properties": {
            "args": {
                "type": "string",
                "description": "Git arguments excluding the leading 'git'.",
            }
        },
        "required": ["args"],
    }

    def __init__(self, workspace_root: Path, shell_runner: ShellRunner) -> None:
        super().__init__(workspace_root)
        self.shell_runner = shell_runner

    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult:
        try:
            args = shlex.split(str(payload["args"]))
        except ValueError as exc:
            return ToolExecutionResult(ok=False, content=str(exc))

        result = self.shell_runner.run_argv(["git"] + args, cwd=self.workspace_root)
        output = {
            "command": result.command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        return ToolExecutionResult(ok=result.ok, content=json.dumps(output, ensure_ascii=False))

    def approval_prompt(self, payload: Mapping[str, Any]) -> str:
        return f"Approve git command? git {payload.get('args', '')}".strip()


def build_tools(
    *,
    workspace_root: Path,
    shell_runner: ShellRunner,
    enabled_tools: Optional[tuple] = None,
) -> Dict[str, BaseTool]:
    enabled = set(enabled_tools or ("read_file", "write_file", "git_run"))
    tools: Dict[str, BaseTool] = {}

    if "read_file" in enabled:
        tools["read_file"] = ReadFileTool(workspace_root)
    if "write_file" in enabled:
        tools["write_file"] = WriteFileTool(workspace_root)
    if "git_run" in enabled:
        tools["git_run"] = GitTool(workspace_root, shell_runner)

    return tools
