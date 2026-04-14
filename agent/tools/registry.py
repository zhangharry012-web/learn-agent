from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from agent.config import AgentConfig
from agent.shell import ShellRunner
from agent.tools.base import BaseTool
from agent.tools.exec_tool import ExecTool
from agent.tools.file_tools import EditFileTool, ReadFileTool, WriteFileTool
from agent.tools.git_inspect_tool import GitInspectTool
from agent.tools.git_tool import GitTool
from agent.tools.inspect_tool import InspectPathTool
from agent.tools.read_only_command_tool import ReadOnlyCommandTool
from agent.tools.verify_command_tool import VerifyCommandTool


def build_tools(
    *,
    workspace_root: Path,
    shell_runner: ShellRunner,
    enabled_tools: Optional[tuple] = None,
    config: Optional[AgentConfig] = None,
    verify_event_logger=None,
) -> Dict[str, BaseTool]:
    resolved_config = config or AgentConfig()
    enabled = set(
        enabled_tools
        or (
            'read_file',
            'write_file',
            'edit_file',
            'git_run',
            'git_inspect',
            'exec',
            'inspect_path',
            'read_only_command',
            'verify_command',
        )
    )
    tools: Dict[str, BaseTool] = {}

    if 'read_file' in enabled:
        tools['read_file'] = ReadFileTool(workspace_root)
    if 'write_file' in enabled:
        tools['write_file'] = WriteFileTool(workspace_root)
    if 'edit_file' in enabled:
        tools['edit_file'] = EditFileTool(workspace_root)
    if 'git_run' in enabled:
        tools['git_run'] = GitTool(workspace_root, shell_runner)
    if 'git_inspect' in enabled:
        tools['git_inspect'] = GitInspectTool(workspace_root, shell_runner)
    if 'exec' in enabled:
        tools['exec'] = ExecTool(workspace_root, shell_runner)
    if 'inspect_path' in enabled:
        tools['inspect_path'] = InspectPathTool(workspace_root, shell_runner)
    if 'read_only_command' in enabled:
        tools['read_only_command'] = ReadOnlyCommandTool(workspace_root, shell_runner)
    if 'verify_command' in enabled:
        tools['verify_command'] = VerifyCommandTool(workspace_root, shell_runner, resolved_config, event_logger=verify_event_logger)

    return tools
