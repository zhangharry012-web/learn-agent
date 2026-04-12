import tempfile
import unittest
from pathlib import Path

from agent.config import AgentConfig
from agent.core import Agent
from agent.llm import LLMResponse, ToolCall
from agent.shell import ShellResult
from tests.helpers import FakeLLM, FakeShellRunner


class AgentLLMTests(unittest.TestCase):
    def test_write_requires_approval_then_executes(self):
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
                    ),
                    LLMResponse(text='File written.', tool_calls=[], stop_reason='end_turn'),
                ]
            )
            agent = Agent(llm=llm, config=AgentConfig(llm_api_key='test'), workspace_root=root)
            first = agent.handle('create a draft file')
            self.assertTrue(first.awaiting_confirmation)
            self.assertIn('Approve file write?', first.message)
            second = agent.handle('yes')
            self.assertTrue(second.ok)
            self.assertEqual((root / 'draft.txt').read_text(encoding='utf-8'), 'generated')
            self.assertEqual(second.message, 'File written.')

    def test_git_requires_approval_and_can_be_denied(self):
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
        agent = Agent(
            llm=llm,
            shell_runner=FakeShellRunner(shell_result),
            config=AgentConfig(llm_api_key='test'),
        )
        first = agent.handle('show git status')
        self.assertTrue(first.awaiting_confirmation)
        self.assertIn('Approve git command?', first.message)
        second = agent.handle('no')
        self.assertTrue(second.ok)
        self.assertEqual(second.message, 'Git action was not executed.')
        last_message = llm.calls[-1]['messages'][-1]
        self.assertEqual(last_message['role'], 'tool_result')
        self.assertTrue(last_message['results'][0].is_error)

    def test_without_llm_falls_back_to_shell(self):
        agent = Agent(config=AgentConfig(llm_api_key=''))
        response = agent.handle('echo hello')
        self.assertTrue(response.ok)
        self.assertEqual(response.stdout, 'hello')
