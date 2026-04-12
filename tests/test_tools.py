import json
import tempfile
import unittest
from pathlib import Path

from agent.shell import ShellResult
from agent.tools import EditFileTool, ExecTool, GitTool, ReadFileTool, WriteFileTool, build_tools
from tests.helpers import FakeShellRunner


class ToolTests(unittest.TestCase):
    def test_read_file_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'notes.txt'
            path.write_text('alpha\nbeta\ngamma\n', encoding='utf-8')

            tool = ReadFileTool(root)
            result = tool.execute({'path': 'notes.txt', 'start_line': 2, 'end_line': 3})

            self.assertTrue(result.ok)
            payload = json.loads(result.content)
            self.assertEqual(payload['content'], 'beta\ngamma')

    def test_write_file_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = WriteFileTool(root)

            result = tool.execute({'path': 'out.txt', 'content': 'hello', 'mode': 'overwrite'})

            self.assertTrue(result.ok)
            self.assertEqual((root / 'out.txt').read_text(encoding='utf-8'), 'hello')

    def test_edit_file_tool_replaces_first_match_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'notes.txt'
            path.write_text('alpha beta beta', encoding='utf-8')

            tool = EditFileTool(root)
            result = tool.execute({'path': 'notes.txt', 'search': 'beta', 'replace': 'gamma'})

            self.assertTrue(result.ok)
            payload = json.loads(result.content)
            self.assertEqual(payload['replacements'], 1)
            self.assertFalse(payload['replace_all'])
            self.assertEqual(path.read_text(encoding='utf-8'), 'alpha gamma beta')

    def test_edit_file_tool_can_replace_all_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'notes.txt'
            path.write_text('beta beta beta', encoding='utf-8')

            tool = EditFileTool(root)
            result = tool.execute(
                {'path': 'notes.txt', 'search': 'beta', 'replace': 'gamma', 'replace_all': True}
            )

            self.assertTrue(result.ok)
            payload = json.loads(result.content)
            self.assertEqual(payload['replacements'], 3)
            self.assertTrue(payload['replace_all'])
            self.assertEqual(path.read_text(encoding='utf-8'), 'gamma gamma gamma')

    def test_edit_file_tool_rejects_missing_search_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'notes.txt').write_text('alpha', encoding='utf-8')

            tool = EditFileTool(root)
            result = tool.execute({'path': 'notes.txt', 'search': '', 'replace': 'beta'})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Search text must not be empty.')

    def test_exec_tool_uses_shell_runner_with_workspace_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell_runner = FakeShellRunner(
                ShellResult(command='pwd', returncode=0, stdout='ok', stderr='')
            )
            tool = ExecTool(root, shell_runner)

            result = tool.execute({'command': 'pwd'})

            self.assertTrue(result.ok)
            self.assertEqual(shell_runner.command_calls, [{'command': 'pwd', 'cwd': root}])
            payload = json.loads(result.content)
            self.assertEqual(payload['stdout'], 'ok')

    def test_git_tool_uses_shell_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell_runner = FakeShellRunner(
                ShellResult(command='git status --short', returncode=0, stdout='M a.py', stderr='')
            )
            tool = GitTool(root, shell_runner)

            result = tool.execute({'args': 'status --short'})

            self.assertTrue(result.ok)
            self.assertEqual(shell_runner.argv_calls[0]['argv'], ['git', 'status', '--short'])

    def test_build_tools_includes_new_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell_runner = FakeShellRunner(
                ShellResult(command='echo ok', returncode=0, stdout='ok', stderr='')
            )

            tools = build_tools(workspace_root=root, shell_runner=shell_runner)

            self.assertEqual(
                set(tools),
                {'read_file', 'write_file', 'edit_file', 'git_run', 'exec'},
            )
