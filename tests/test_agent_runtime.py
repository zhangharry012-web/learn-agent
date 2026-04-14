import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple

from agent.config import AgentConfig
from agent.core import Agent
from agent.llm import LLMResponse, TokenUsage, ToolCall
from agent.llm.types import LLMToolCallFormatError
from agent.runtime.agent import LLM_PANIC_RETRY_MESSAGE
from agent.runtime.events import (
    COMMAND_RECEIVED,
    LLM_PANIC,
    LLM_RESPONSE_COMPLETED,
    LLM_LOOP_LIMIT_EXCEEDED,
    SESSION_SUMMARY,
    SHELL_EXECUTION_COMPLETED,
    VERIFY_EXECUTION_COMPLETED,
    VERIFY_EXECUTION_REJECTED,
    VERIFY_EXECUTION_REQUESTED,
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


class RetryFormatErrorLLM:
    has_failed_once = False

    def __init__(self):
        self.calls = []
        self.max_tokens = 8192

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if not RetryFormatErrorLLM.has_failed_once:
            RetryFormatErrorLLM.has_failed_once = True
            raise LLMToolCallFormatError('Invalid tool arguments from provider')
        return LLMResponse(text='Recovered after retry.', tool_calls=[], stop_reason='end_turn')


class AlwaysPanicLLM:
    def __init__(self):
        self.calls = []
        self.max_tokens = 8192

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError('boom')


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

    def test_session_summary_is_logged_on_exit_with_llm_and_tool_totals(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            shell_runner = FakeShellRunner(
                ShellResult(command='python -m unittest tests.test_tools', returncode=0, stdout='ok', stderr='')
            )
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
                    LLMResponse(
                        text='File written.',
                        tool_calls=[],
                        stop_reason='end_turn',
                        usage=TokenUsage(input_tokens=8, output_tokens=4, total_tokens=12),
                    ),
                    LLMResponse(
                        text='',
                        tool_calls=[
                            ToolCall(
                                id='toolu_verify_1',
                                name='verify_command',
                                arguments={'argv': ['python', '-m', 'unittest', 'tests.test_tools']},
                            )
                        ],
                        stop_reason='tool_use',
                        usage=TokenUsage(input_tokens=12, output_tokens=6, total_tokens=18),
                    ),
                    LLMResponse(
                        text='Verification completed.',
                        tool_calls=[],
                        stop_reason='end_turn',
                        usage=TokenUsage(input_tokens=7, output_tokens=3, total_tokens=10),
                    ),
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

            first = agent.handle('create a draft file')
            second = agent.handle('run python verification')
            exit_response = agent.handle('exit')

            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            self.assertTrue(exit_response.ok)
            self.assertTrue(exit_response.should_exit)

            events_path = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))[0]
            events = _read_events(events_path)
            summary_event = next(event for event in events if event['event_type'] == SESSION_SUMMARY)
            payload = summary_event['payload']
            self.assertEqual(payload['trigger'], 'session_exit')
            self.assertEqual(payload['command'], 'exit')
            self.assertEqual(payload['command_count'], 3)
            self.assertEqual(payload['llm_call_count'], 4)
            self.assertEqual(payload['tool_call_count'], 2)
            self.assertEqual(payload['tool_call_breakdown'], {'verify_command': 1, 'write_file': 1})
            self.assertEqual(payload['tool_success_count'], 2)
            self.assertEqual(payload['tool_failure_count'], 0)
            self.assertEqual(payload['tool_outcome_breakdown'], {'verify_command': {'ok': 1, 'error': 0}, 'write_file': {'ok': 1, 'error': 0}})
            self.assertEqual(payload['token_usage']['input_tokens'], 37)
            self.assertIsNotNone(exit_response.session_summary)
            self.assertEqual(exit_response.session_summary['tool_success_count'], 2)
            self.assertEqual(payload['token_usage']['output_tokens'], 18)
            self.assertEqual(payload['token_usage']['total_tokens'], 55)

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

    def test_exec_approval_can_be_denied(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            shell_result = ShellResult(command='rm -rf temp', returncode=0, stdout='', stderr='')
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[ToolCall(id='toolu_exec_deny_1', name='exec', arguments={'command': 'rm -rf temp'})],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='Action was not executed.', tool_calls=[], stop_reason='end_turn'),
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
            first = agent.handle('delete temp directory')
            self.assertTrue(first.awaiting_confirmation)
            self.assertIn('Approve shell command?', first.message)
            second = agent.handle('no')
            self.assertTrue(second.ok)
            self.assertEqual(second.message, 'Action was not executed.')
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

    def test_read_only_command_executes_without_approval(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            (root / 'README.md').write_text('alpha\nbeta\n', encoding='utf-8')
            shell_runner = FakeShellRunner(ShellResult(command='wc -l README.md', returncode=0, stdout='2 README.md\n', stderr=''))
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[ToolCall(id='toolu_read_only_1', name='read_only_command', arguments={'args': 'wc -l README.md'})],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='File summary inspected.', tool_calls=[], stop_reason='end_turn'),
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

            response = agent.handle('count lines in readme')

            self.assertTrue(response.ok)
            self.assertFalse(response.awaiting_confirmation)
            self.assertEqual(response.message, 'File summary inspected.')
            self.assertEqual(shell_runner.argv_calls[0]['argv'], ['wc', '-l', 'README.md'])

    def test_verify_command_executes_without_approval(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            shell_runner = FakeShellRunner(
                ShellResult(command='python -m unittest tests.test_tools', returncode=0, stdout='ok', stderr='')
            )
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[
                            ToolCall(
                                id='toolu_verify_1',
                                name='verify_command',
                                arguments={'argv': ['python', '-m', 'unittest', 'tests.test_tools']},
                            )
                        ],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='Verification completed.', tool_calls=[], stop_reason='end_turn'),
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

            response = agent.handle('run python verification')

            self.assertTrue(response.ok)
            self.assertFalse(response.awaiting_confirmation)
            self.assertEqual(response.message, 'Verification completed.')
            self.assertEqual(shell_runner.argv_calls[0]['argv'], ['python', '-m', 'unittest', 'tests.test_tools'])
            self.assertEqual(shell_runner.argv_calls[0]['timeout'], 120)
            events_path = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))[0]
            events = _read_events(events_path)
            event_types = {event['event_type'] for event in events}
            self.assertIn(VERIFY_EXECUTION_REQUESTED, event_types)
            self.assertIn(VERIFY_EXECUTION_COMPLETED, event_types)

    def test_llm_tool_call_format_error_retries_with_fallback_max_tokens(self):
        RetryFormatErrorLLM.has_failed_once = False
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            config = AgentConfig(
                llm_api_key='test',
                llm_max_tokens=8192,
                llm_fallback_max_tokens=16384,
            )
            agent = Agent(
                llm=RetryFormatErrorLLM(),
                config=config,
                workspace_root=root,
                observability_logger=ObservabilityLogger(root / 'logs' / 'observability'),
            )

            def rebuild(max_tokens=None):
                replacement = RetryFormatErrorLLM()
                replacement.max_tokens = max_tokens or 0
                return replacement

            agent._build_default_llm = rebuild
            response = agent.handle('retry on malformed tool call')

            self.assertTrue(response.ok)
            self.assertEqual(response.message, 'Recovered after retry.')
            self.assertEqual(agent.current_llm_max_tokens, 16384)

    def test_llm_panic_writes_exception_log_and_returns_retry_message(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=AlwaysPanicLLM(),
                config=AgentConfig(llm_api_key='test', exception_log_dir='logs/exceptions'),
                workspace_root=root,
                observability_logger=logger,
            )
            response = agent.handle('cause panic')

            self.assertFalse(response.ok)
            self.assertEqual(response.stderr, LLM_PANIC_RETRY_MESSAGE)
            exception_logs = sorted((root / 'logs' / 'exceptions').rglob('*.json'))
            self.assertTrue(exception_logs)
            payload = json.loads(exception_logs[0].read_text(encoding='utf-8'))
            self.assertEqual(payload['error_type'], 'RuntimeError')
            self.assertIn('boom', payload['error_message'])
            events_path = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))[0]
            events = _read_events(events_path)
            panic_event = next(event for event in events if event['event_type'] == LLM_PANIC)
            self.assertEqual(panic_event['payload']['error_type'], 'RuntimeError')



class AgentSessionSummaryOutcomeTests(unittest.TestCase):
    def test_session_summary_tracks_tool_success_and_failure_breakdown(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[
                            ToolCall(
                                id='toolu_exec_1',
                                name='exec',
                                arguments={'command': 'pwd'},
                            )
                        ],
                        stop_reason='tool_use',
                        usage=TokenUsage(input_tokens=9, output_tokens=3, total_tokens=12),
                    ),
                    LLMResponse(
                        text='Command denied.',
                        tool_calls=[],
                        stop_reason='end_turn',
                        usage=TokenUsage(input_tokens=4, output_tokens=2, total_tokens=6),
                    ),
                ]
            )
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                shell_runner=FakeShellRunner(ShellResult(command='pwd', returncode=0, stdout='/tmp/work', stderr='')),
                config=AgentConfig(llm_api_key='test'),
                workspace_root=root,
                observability_logger=logger,
            )

            first = agent.handle('run pwd')
            second = agent.handle('no')
            exit_response = agent.handle('exit')

            self.assertTrue(first.awaiting_confirmation)
            self.assertTrue(second.ok)
            self.assertTrue(exit_response.should_exit)
            self.assertEqual(exit_response.session_summary['tool_call_count'], 1)
            self.assertEqual(exit_response.session_summary['tool_success_count'], 0)
            self.assertEqual(exit_response.session_summary['tool_failure_count'], 1)
            self.assertEqual(exit_response.session_summary['tool_outcome_breakdown'], {'exec': {'ok': 0, 'error': 1}})
            self.assertEqual(exit_response.session_summary['token_usage']['total_tokens'], 18)

            events_path = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))[0]
            events = _read_events(events_path)
            summary_event = next(event for event in events if event['event_type'] == SESSION_SUMMARY)
            payload = summary_event['payload']
            self.assertEqual(payload['tool_success_count'], 0)
            self.assertEqual(payload['tool_failure_count'], 1)
            self.assertEqual(payload['tool_outcome_breakdown'], {'exec': {'ok': 0, 'error': 1}})



class AgentVerifyObservabilityTests(unittest.TestCase):
    def test_verify_command_rejection_is_logged(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            llm = FakeLLM(
                [
                    LLMResponse(
                        text='',
                        tool_calls=[
                            ToolCall(
                                id='toolu_verify_bad_1',
                                name='verify_command',
                                arguments={'argv': ['python', 'script.py']},
                            )
                        ],
                        stop_reason='tool_use',
                    ),
                    LLMResponse(text='Verification rejected.', tool_calls=[], stop_reason='end_turn'),
                ]
            )
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                shell_runner=FakeShellRunner(ShellResult(command='', returncode=0, stdout='', stderr='')),
                config=AgentConfig(llm_api_key='test'),
                workspace_root=root,
                observability_logger=logger,
            )

            response = agent.handle('run unsupported python script')

            self.assertTrue(response.ok)
            self.assertEqual(response.message, 'Verification rejected.')
            events_path = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))[0]
            events = _read_events(events_path)
            rejected = next(event for event in events if event['event_type'] == VERIFY_EXECUTION_REJECTED)
            self.assertIn('Only python -m unittest and python -m pytest are allowed.', rejected['payload']['error'])


class AgentToolLoopLimitTests(unittest.TestCase):
    def test_custom_loop_limit_is_respected(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            responses = []
            for i in range(3):
                responses.append(
                    LLMResponse(
                        text='',
                        tool_calls=[
                            ToolCall(
                                id=f'toolu_read_{i}',
                                name='read_file',
                                arguments={'path': 'README.md'},
                            )
                        ],
                        stop_reason='tool_use',
                    )
                )
            llm = FakeLLM(responses)
            (root / 'README.md').write_text('hello', encoding='utf-8')
            logger = ObservabilityLogger(root / 'logs' / 'observability')
            agent = Agent(
                llm=llm,
                config=AgentConfig(llm_api_key='test', llm_max_tool_steps=2),
                workspace_root=root,
                observability_logger=logger,
            )
            response = agent.handle('read many files')
            self.assertFalse(response.ok)
            self.assertIn('maximum tool interaction limit', response.stderr)
            events_path = sorted((root / 'logs' / 'observability' / 'events').rglob('*.jsonl'))[0]
            events = _read_events(events_path)
            limit_event = next(event for event in events if event['event_type'] == LLM_LOOP_LIMIT_EXCEEDED)
            self.assertEqual(limit_event['payload']['max_steps'], 2)

    def test_default_loop_limit_is_25(self):
        config = AgentConfig(llm_api_key='test')
        self.assertEqual(config.llm_max_tool_steps, 25)
