import json
import tempfile
import unittest
from pathlib import Path

from agent.shell import ShellResult
from agent.tools import GitTool, ReadFileTool, WriteFileTool
from tests.helpers import FakeShellRunner


class ToolTests(unittest.TestCase):
    def test_read_file_tool(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            file_path = root / 'notes.txt'
            file_path.write_text('a\nb\nc\n', encoding='utf-8')
            tool = ReadFileTool(root)
            result = tool.execute({'path': 'notes.txt', 'start_line': 2, 'end_line': 3})
            self.assertTrue(result.ok)
            payload = json.loads(result.content)
            self.assertEqual(payload['content'], 'b\nc')

    def test_write_file_tool(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            tool = WriteFileTool(root)
            result = tool.execute({'path': 'out.txt', 'content': 'hello', 'mode': 'overwrite'})
            self.assertTrue(result.ok)
            self.assertEqual((root / 'out.txt').read_text(encoding='utf-8'), 'hello')

    def test_git_tool_uses_shell_runner(self):
        shell_result = ShellResult(command='git status --short', returncode=0, stdout='M README.md', stderr='')
        runner = FakeShellRunner(shell_result)
        tool = GitTool(Path.cwd(), runner)
        result = tool.execute({'args': 'status --short'})
        self.assertTrue(result.ok)
        self.assertEqual(runner.argv_calls[0]['argv'], ['git', 'status', '--short'])
