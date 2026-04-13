from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.exec_tool import ExecTool
from agent.tools.file_tools import EditFileTool, ReadFileTool, WriteFileTool
from agent.tools.git_tool import GitTool
from agent.tools.inspect_tool import InspectPathTool


def build_tools(
    *,
    workspace_root: Path,
    shell_runner: ShellRunner,
    enabled_tools: Optional[tuple] = None,
) -> Dict[str, BaseTool]:
    enabled = set(enabled_tools or ('read_file', 'write_file', 'edit_file', 'git_run', 'exec', 'inspect_path'))
    tools: Dict[str, BaseTool] = {}

    if 'read_file' in enabled:
        tools['read_file'] = ReadFileTool(workspace_root)
    if 'write_file' in enabled:
        tools['write_file'] = WriteFileTool(workspace_root)
    if 'edit_file' in enabled:
        tools['edit_file'] = EditFileTool(workspace_root)
    if 'git_run' in enabled:
        tools['git_run'] = GitTool(workspace_root, shell_runner)
    if 'exec' in enabled:
        tools['exec'] = ExecTool(workspace_root, shell_runner)
    if 'inspect_path' in enabled:
        tools['inspect_path'] = InspectPathTool(workspace_root, shell_runner)

    return tools
