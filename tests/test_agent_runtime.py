import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple

from agent.config import AgentConfig
from agent.core import Agent
from agent.llm import LLMResponse, TokenUsage, ToolCall
from agent.runtime.events import (
    COMMAND_RECEIVED,
    LLM_RESPONSE_COMPLETED,
    SHELL_EXECUTION_COMPLETED,
    TOOL_APPROVAL_COMPLETED,
    TOOL_EXECUTION_COMPLETED,
)
from agent.runtime.observability import ObservabilityLogger
from agent.shell import ShellResult
from tests.helpers import FakeLLM, FakeShellRunner


def _read_events(path: Path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def _utc_partition_paths(root: Path, session_id: str, moment: datetime) -> Tuple[Path, Path]:
    date_part = moment.strftime('%Y-%m-%d')
    hour_file = moment.strftime('%H') + '.jsonl'
    events_path = root / 'logs' / 'observability' / 'events' / date_part / hour_file
    session_path = root / 'logs' / 'observability' / 'sessions' / session_id / date_part / hour_file
    return events_path, session_path


class AgentLLMTests(unittest.TestCase):
    def test_write_executes_without_approval(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[
                            ToolCall(
                                id='toolu_write_1',
                                name='write_file',
                                arguments={'path': 'draft.txt', 'content': 'generated', 'mode': 'overwrite'},
                            )
                        ],
                        stop_reason='tool_use',
                        usage=TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
                    ),
                    LLMResponse(text='File written.', tool_calls=[], stop_reason='end_turn'),
                ]
            )
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                config=AgentConfig(llm_api_key='test'),
                workspace_root=root,
                observability_logger=logger,
            )
            first = agent.handle('create a draft file')
            self.assertTrue(first.ok)
            self.assertFalse(first.awaiting_confirmation)
            self.assertEqual((root / 'draft.txt').read_text(encoding='utf-8'), 'generated')
            self.assertEqual(first.message, 'File written.')
            moment = datetime.now(timezone.utc)
            events_glob = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))
            self.assertTrue(events_glob)
            events = _read_events(events_glob[0])
            session_id = events[0]['session_id']
            events_path, session_path = _utc_partition_paths(root, session_id, moment)
            self.assertTrue(events_path.exists())
            self.assertTrue(session_path.exists())
            session_events = _read_events(session_path)
            filtered_global_events = [event for event in _read_events(events_path) if event['session_id'] == session_id]
            event_types = {event['event_type'] for event in filtered_global_events}
            self.assertEqual(len(filtered_global_events), len(session_events))
            self.assertIn(COMMAND_RECEIVED, event_types)
            self.assertIn(LLM_RESPONSE_COMPLETED, event_types)
            self.assertIn(TOOL_EXECUTION_COMPLETED, event_types)
            llm_event = next(event for event in filtered_global_events if event['event_type'] == LLM_RESPONSE_COMPLETED)
            self.assertEqual(llm_event['payload']['usage']['total_tokens'], 15)
            self.assertRegex(llm_event['timestamp'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$')

    def test_edit_executes_without_approval(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            (root / 'draft.txt').write_text('alpha beta', encoding='utf-8')
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[
                            ToolCall(
                                id='toolu_edit_1',
                                name='edit_file',
                                arguments={'path': 'draft.txt', 'search': 'beta', 'replace': 'gamma'},
                            )
                        ],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='File edited.', tool_calls=[], stop_reason='end_turn'),
                ]
            )
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                config=AgentConfig(llm_api_key='test'),
                workspace_root=root,
                observability_logger=logger,
            )
            first = agent.handle('update the draft file')
            self.assertTrue(first.ok)
            self.assertFalse(first.awaiting_confirmation)
            self.assertEqual((root / 'draft.txt').read_text(encoding='utf-8'), 'alpha gamma')
            self.assertEqual(first.message, 'File edited.')

    def test_exec_requires_approval_then_executes(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            shell_result = ShellResult(command='pwd', returncode=0, stdout='/tmp/work', stderr='')
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[ToolCall(id='toolu_exec_1', name='exec', arguments={'command': 'pwd'})],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='Command executed.', tool_calls=[], stop_reason='end_turn'),
                ]
            )
            shell_runner = FakeShellRunner(shell_result)
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                shell_runner=shell_runner,
                config=AgentConfig(llm_api_key='test'),
                workspace_root=root,
                observability_logger=logger,
            )
            first = agent.handle('run pwd')
            self.assertTrue(first.awaiting_confirmation)
            self.assertIn('Approve shell command?', first.message)
            second = agent.handle('yes')
            self.assertTrue(second.ok)
            self.assertEqual(second.message, 'Command executed.')
            self.assertEqual(shell_runner.command_calls[0]['command'], 'pwd')

    def test_git_requires_approval_and_can_be_denied(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            shell_result = ShellResult(command='git status --short', returncode=0, stdout='', stderr='')
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[ToolCall(id='toolu_git_1', name='git_run', arguments={'args': 'status --short'})],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='Git action was not executed.', tool_calls=[], stop_reason='end_turn'),
                ]
            )
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                shell_runner=FakeShellRunner(shell_result),
                config=AgentConfig(llm_api_key='test'),
                workspace_root=root,
                observability_logger=logger,
            )
            first = agent.handle('show git status')
            self.assertTrue(first.awaiting_confirmation)
            self.assertIn('Approve git command?', first.message)
            second = agent.handle('no')
            self.assertTrue(second.ok)
            self.assertEqual(second.message, 'Git action was not executed.')
            events_path = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))[0]
            events = _read_events(events_path)
            decision = next(event for event in events if event['event_type'] == TOOL_APPROVAL_COMPLETED)
            self.assertFalse(decision['payload']['approved'])
            last_message = llm.calls[-1]['messages'][-1]
            self.assertEqual(last_message['role'], 'tool_result')
            self.assertTrue(last_message['results'][0].is_error)

    def test_without_llm_falls_back_to_shell_and_logs(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            shell_runner = FakeShellRunner(ShellResult(command='echo hello', returncode=0, stdout='hello', stderr=''))
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                config=AgentConfig(llm_api_key=''),
                shell_runner=shell_runner,
                workspace_root=root,
                observability_logger=logger,
            )
            response = agent.handle('echo hello')
            self.assertTrue(response.ok)
            self.assertEqual(response.stdout, 'hello')
            events_path = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))[0]
            events = _read_events(events_path)
            self.assertIn(SHELL_EXECUTION_COMPLETED, {event['event_type'] for event in events})

    def test_cleanup_removes_expired_rotated_logs_and_prunes_empty_directories(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            logger = ObservabilityLogger(root / 'logs' / 'observability', retention_hours=1)
            stale_moment = datetime.now(timezone.utc) - timedelta(hours=3)
            stale_date = stale_moment.strftime('%Y-%m-%d')
            stale_hour = stale_moment.strftime('%H') + '.jsonl'
            stale_events = root / 'logs' / 'observability' / 'events' / stale_date / stale_hour
            stale_session_dir = root / 'logs' / 'observability' / 'sessions' / 'old-session' / stale_date
            stale_session = stale_session_dir / stale_hour
            stale_events.parent.mkdir(parents=True, exist_ok=True)
            stale_session.parent.mkdir(parents=True, exist_ok=True)
            stale_events.write_text('{"old": true}\n', encoding='utf-8')
            stale_session.write_text('{"old": true}\n', encoding='utf-8')
            logger.log_event(COMMAND_RECEIVED, 'active-session', {'command': 'hello'})
            self.assertFalse(stale_events.exists())
            self.assertFalse(stale_session.exists())
            self.assertFalse(stale_session_dir.exists())
            current_paths = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))
            self.assertTrue(current_paths)

    def test_cleanup_skips_malformed_paths_and_keeps_recent_logs(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            logger = ObservabilityLogger(root / 'logs' / 'observability', retention_hours=1)
            malformed = root / 'logs' / 'observability' / 'events' / 'bad-date' / 'nope.jsonl'
            recent_moment = datetime.now(timezone.utc)
            _, recent_session_path = _utc_partition_paths(root, 'active-session', recent_moment)
            malformed.parent.mkdir(parents=True, exist_ok=True)
            recent_session_path.parent.mkdir(parents=True, exist_ok=True)
            malformed.write_text('{"bad": true}\n', encoding='utf-8')
            recent_session_path.write_text('{"recent": true}\n', encoding='utf-8')
            logger.log_event(COMMAND_RECEIVED, 'active-session', {'command': 'hello'})
            self.assertTrue(malformed.exists())
            self.assertTrue(recent_session_path.exists())


    def test_inspect_path_executes_without_approval(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            shell_runner = FakeShellRunner(ShellResult(command='pwd', returncode=0, stdout=str(root), stderr=''))
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[ToolCall(id='toolu_inspect_1', name='inspect_path', arguments={'action': 'pwd'})],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='Workspace inspected.', tool_calls=[], stop_reason='end_turn'),
                ]
            )
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                shell_runner=shell_runner,
                config=AgentConfig(llm_api_key='test'),
                workspace_root=root,
                observability_logger=logger,
            )

            response = agent.handle('show me the workspace path')

            self.assertTrue(response.ok)
            self.assertFalse(response.awaiting_confirmation)
            self.assertEqual(response.message, 'Workspace inspected.')
            self.assertEqual(shell_runner.argv_calls, [])


    def test_write_outside_project_root_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[
                            ToolCall(
                                id='toolu_write_escape_1',
                                name='write_file',
                                arguments={'path': '../escape.txt', 'content': 'bad', 'mode': 'overwrite'},
                            )
                        ],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='Write rejected.', tool_calls=[], stop_reason='end_turn'),
                ]
            )
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                config=AgentConfig(llm_api_key='test'),
                workspace_root=root,
                observability_logger=logger,
            )

            response = agent.handle('write outside root')

            self.assertTrue(response.ok)
            self.assertEqual(response.message, 'Write rejected.')
            self.assertFalse((root.parent / 'escape.txt').exists())


    def test_git_inspect_executes_without_approval(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            shell_runner = FakeShellRunner(ShellResult(command='git status --short', returncode=0, stdout='M README.md', stderr=''))
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[ToolCall(id='toolu_git_inspect_1', name='git_inspect', arguments={'args': 'status --short'})],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='Repository inspected.', tool_calls=[], stop_reason='end_turn'),
                ]
            )
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                shell_runner=shell_runner,
                config=AgentConfig(llm_api_key='test'),
                workspace_root=root,
                observability_logger=logger,
            )

            response = agent.handle('show me git status')

            self.assertTrue(response.ok)
            self.assertFalse(response.awaiting_confirmation)
            self.assertEqual(response.message, 'Repository inspected.')
            self.assertEqual(shell_runner.argv_calls[0]['argv'], ['git', 'status', '--short'])
