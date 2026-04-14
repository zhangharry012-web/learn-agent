import json
import tempfile
import unittest
from pathlib import Path

from agent.config import AgentConfig
from agent.shell import ShellResult
from agent.tools import (
    EditFileTool,
    ExecTool,
    GitInspectTool,
    GitTool,
    InspectPathTool,
    ReadFileTool,
    ReadOnlyCommandTool,
    VerifyCommandTool,
    WriteFileTool,
    build_tools,
)
from tests.helpers import FakeShellRunner
from agent.runtime.events import (
    VERIFY_EXECUTION_COMPLETED,
    VERIFY_EXECUTION_REJECTED,
    VERIFY_EXECUTION_REQUESTED,
)


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
            self.assertEqual(shell_runner.command_calls, [{'command': 'pwd', 'cwd': root, 'timeout': None}])
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

            tools = build_tools(workspace_root=root, shell_runner=shell_runner, config=AgentConfig())

            self.assertEqual(
                set(tools),
                {
                    'read_file',
                    'write_file',
                    'edit_file',
                    'git_run',
                    'git_inspect',
                    'exec',
                    'inspect_path',
                    'read_only_command',
                    'verify_command',
                },
            )

    def test_inspect_path_tool_uses_argv_for_ls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell_runner = FakeShellRunner(
                ShellResult(command='ls -1 .', returncode=0, stdout='a.py\nb.py', stderr='')
            )
            tool = InspectPathTool(root, shell_runner)

            result = tool.execute({'action': 'ls', 'path': '.'})

            self.assertTrue(result.ok)
            self.assertEqual(shell_runner.argv_calls[0]['argv'][:2], ['ls', '-1'])
            payload = json.loads(result.content)
            self.assertEqual(payload['entries'], ['a.py', 'b.py'])

    def test_inspect_path_tool_uses_argv_for_find(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell_runner = FakeShellRunner(
                ShellResult(command='find .', returncode=0, stdout=str(root) + '\n' + str(root / 'agent'), stderr='')
            )
            tool = InspectPathTool(root, shell_runner)

            result = tool.execute({'action': 'find', 'path': '.', 'max_depth': 2})

            self.assertTrue(result.ok)
            self.assertEqual(shell_runner.argv_calls[0]['argv'][:3], ['find', str(root), '-maxdepth'])
            payload = json.loads(result.content)
            self.assertEqual(payload['entries'], ['.', 'agent'])

    def test_inspect_path_tool_rejects_missing_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = InspectPathTool(root, FakeShellRunner(ShellResult(command='pwd', returncode=0, stdout='', stderr='')))

            result = tool.execute({'action': 'ls', 'path': 'missing'})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Target path does not exist.')

    def test_write_file_tool_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = WriteFileTool(root)

            result = tool.execute({'path': '../escape.txt', 'content': 'hello', 'mode': 'overwrite'})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Path escapes the workspace root.')

    def test_edit_file_tool_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = EditFileTool(root)

            result = tool.execute({'path': '../escape.txt', 'search': 'a', 'replace': 'b'})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Path escapes the workspace root.')

    def test_inspect_path_tool_pwd_returns_project_root_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = InspectPathTool(root, FakeShellRunner(ShellResult(command='pwd', returncode=0, stdout=str(root), stderr='')))

            result = tool.execute({'action': 'pwd'})

            self.assertTrue(result.ok)
            payload = json.loads(result.content)
            self.assertEqual(payload['stdout'], '.')
            self.assertEqual(payload['stderr'], '')

    def test_git_inspect_tool_allows_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell_runner = FakeShellRunner(
                ShellResult(command='git status --short', returncode=0, stdout='M a.py', stderr='')
            )
            tool = GitInspectTool(root, shell_runner)

            result = tool.execute({'args': 'status --short'})

            self.assertTrue(result.ok)
            self.assertEqual(shell_runner.argv_calls[0]['argv'], ['git', 'status', '--short'])

    def test_git_inspect_tool_rejects_mutating_subcommand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = GitInspectTool(root, FakeShellRunner(ShellResult(command='git add .', returncode=0, stdout='', stderr='')))

            result = tool.execute({'args': 'add .'})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Only read-only git inspect commands are allowed.')

    def test_read_only_command_tool_runs_head_without_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'notes.txt'
            target.write_text('alpha\nbeta\n', encoding='utf-8')
            shell_runner = FakeShellRunner(
                ShellResult(command='head -n 2 notes.txt', returncode=0, stdout='alpha\nbeta\n', stderr='')
            )
            tool = ReadOnlyCommandTool(root, shell_runner)

            result = tool.execute({'args': 'head -n 2 notes.txt'})

            self.assertTrue(result.ok)
            self.assertEqual(shell_runner.argv_calls[0]['argv'], ['head', '-n', '2', 'notes.txt'])
            payload = json.loads(result.content)
            self.assertEqual(payload['stdout'], 'alpha\nbeta')

    def test_read_only_command_tool_rejects_cat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'notes.txt').write_text('alpha\n', encoding='utf-8')
            tool = ReadOnlyCommandTool(
                root,
                FakeShellRunner(ShellResult(command='cat notes.txt', returncode=0, stdout='alpha\n', stderr='')),
            )

            result = tool.execute({'args': 'cat notes.txt'})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Use read_file for direct file contents instead of cat.')

    def test_read_only_command_tool_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = ReadOnlyCommandTool(root, FakeShellRunner(ShellResult(command='stat ../escape.txt', returncode=0, stdout='', stderr='')))

            result = tool.execute({'args': 'stat ../escape.txt'})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Path escapes the workspace root.')

    def test_verify_command_tool_runs_python_unittest_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell_runner = FakeShellRunner(
                ShellResult(command='python -m unittest tests.test_tools', returncode=0, stdout='ok', stderr='')
            )
            tool = VerifyCommandTool(root, shell_runner, AgentConfig())

            result = tool.execute({'argv': ['python', '-m', 'unittest', 'tests.test_tools']})

            self.assertTrue(result.ok)
            self.assertEqual(shell_runner.argv_calls[0]['argv'], ['python', '-m', 'unittest', 'tests.test_tools'])
            self.assertEqual(shell_runner.argv_calls[0]['timeout'], 120)
            payload = json.loads(result.content)
            self.assertEqual(payload['rule_id'], 'python-unittest')

    def test_verify_command_tool_rejects_shell_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = VerifyCommandTool(root, FakeShellRunner(ShellResult(command='', returncode=0, stdout='', stderr='')), AgentConfig())

            result = tool.execute({'argv': ['python', '-m', 'unittest', 'tests.test_tools;rm']})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Shell composition tokens are not allowed in verify_command.')

    def test_verify_command_tool_rejects_unsupported_python_script_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tool = VerifyCommandTool(root, FakeShellRunner(ShellResult(command='', returncode=0, stdout='', stderr='')), AgentConfig())

            result = tool.execute({'argv': ['python', 'script.py']})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Only python -m unittest and python -m pytest are allowed.')

    def test_verify_command_tool_uses_repo_policy_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_dir = root / '.agent'
            policy_dir.mkdir()
            (policy_dir / 'verify-policy.json').write_text(
                json.dumps(
                    {
                        'version': 1,
                        'allow': [
                            {
                                'id': 'repo-npm-lint',
                                'argv_exact': ['npm', 'run', 'lint'],
                                'cwd': '.',
                                'max_timeout_sec': 33,
                            }
                        ],
                        'deny_keywords': ['publish'],
                    }
                ),
                encoding='utf-8',
            )
            shell_runner = FakeShellRunner(
                ShellResult(command='npm run lint', returncode=0, stdout='lint ok', stderr='')
            )
            tool = VerifyCommandTool(root, shell_runner, AgentConfig())

            result = tool.execute({'argv': ['npm', 'run', 'lint']})

            self.assertTrue(result.ok)
            self.assertEqual(shell_runner.argv_calls[0]['timeout'], 33)
            payload = json.loads(result.content)
            self.assertEqual(payload['rule_id'], 'repo-npm-lint')

    def test_verify_command_tool_rejects_when_repo_policy_requires_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_dir = root / '.agent'
            policy_dir.mkdir()
            (policy_dir / 'verify-policy.json').write_text(
                json.dumps({'version': 1, 'allow': [], 'deny_keywords': []}),
                encoding='utf-8',
            )
            tool = VerifyCommandTool(
                root,
                FakeShellRunner(ShellResult(command='', returncode=0, stdout='', stderr='')),
                AgentConfig(),
            )

            result = tool.execute({'argv': ['go', 'test', './...']})

            self.assertFalse(result.ok)
            self.assertEqual(result.content, 'Verify command is not allowed by the repository policy.')



class VerifyCommandObservabilityTests(unittest.TestCase):
    def test_verify_command_tool_emits_requested_and_completed_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shell_runner = FakeShellRunner(
                ShellResult(command='python -m unittest tests.test_tools', returncode=0, stdout='ok', stderr='')
            )
            events = []
            tool = VerifyCommandTool(
                root,
                shell_runner,
                AgentConfig(),
                event_logger=lambda event_type, payload: events.append((event_type, dict(payload))),
            )

            result = tool.execute({'argv': ['python', '-m', 'unittest', 'tests.test_tools'], 'reason': 'validate change'})

            self.assertTrue(result.ok)
            self.assertEqual([item[0] for item in events], [VERIFY_EXECUTION_REQUESTED, VERIFY_EXECUTION_COMPLETED])
            self.assertEqual(events[0][1]['reason'], 'validate change')
            self.assertEqual(events[1][1]['rule_id'], 'python-unittest')
            self.assertEqual(events[1][1]['returncode'], 0)

    def test_verify_command_tool_emits_rejected_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = []
            tool = VerifyCommandTool(
                root,
                FakeShellRunner(ShellResult(command='', returncode=0, stdout='', stderr='')),
                AgentConfig(),
                event_logger=lambda event_type, payload: events.append((event_type, dict(payload))),
            )

            result = tool.execute({'argv': ['python', 'script.py'], 'reason': 'bad verify'})

            self.assertFalse(result.ok)
            self.assertEqual([item[0] for item in events], [VERIFY_EXECUTION_REQUESTED, VERIFY_EXECUTION_REJECTED])
            self.assertIn('Only python -m unittest and python -m pytest are allowed.', events[1][1]['error'])
