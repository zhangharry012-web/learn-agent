from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.file_tools import ReadFileTool, WriteFileTool
from agent.tools.git_tool import GitTool


def build_tools(
    *,
    workspace_root: Path,
    shell_runner: ShellRunner,
    enabled_tools: Optional[tuple] = None,
) -> Dict[str, BaseTool]:
    enabled = set(enabled_tools or ('read_file', 'write_file', 'git_run'))
    tools: Dict[str, BaseTool] = {}

    if 'read_file' in enabled:
        tools['read_file'] = ReadFileTool(workspace_root)
    if 'write_file' in enabled:
        tools['write_file'] = WriteFileTool(workspace_root)
    if 'git_run' in enabled:
        tools['git_run'] = GitTool(workspace_root, shell_runner)

    return tools
