import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.config import AgentConfig
from agent.core import Agent
from agent.llm import BaseLLMClient, LLMResponse, ToolCall, create_llm
from agent.llm.anthropic_client import AnthropicLLM
from agent.llm.openai_client import OpenAICompatibleLLM
from agent.policy import CommandPolicy
from agent.shell import ShellResult, ShellRunner
from agent.tools import GitTool, ReadFileTool, WriteFileTool


class FakeLLM(BaseLLMClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, *, system_prompt, messages, tools):
        self.calls.append(
            {
                'system_prompt': system_prompt,
                'messages': messages,
                'tools': tools,
            }
        )
        return self.responses.pop(0)


class FakeShellRunner(ShellRunner):
    def __init__(self, shell_result):
        super().__init__(timeout=1)
        self.shell_result = shell_result
        self.argv_calls = []

    def run_argv(self, argv, cwd=None):
        self.argv_calls.append({'argv': list(argv), 'cwd': cwd})
        return self.shell_result


class CommandPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = CommandPolicy()

    def test_allows_safe_command(self):
        decision = self.policy.evaluate('echo hello')
        self.assertTrue(decision.allowed)

    def test_blocks_rm_command(self):
        decision = self.policy.evaluate('rm -rf tmp')
        self.assertFalse(decision.allowed)


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


class ConfigTests(unittest.TestCase):
    def test_llm_api_key_takes_precedence_over_anthropic_api_key(self):
        with patch.dict(os.environ, {'LLM_API_KEY': 'llm-key', 'ANTHROPIC_API_KEY': 'anth-key'}, clear=False):
            config = AgentConfig(llm_provider='', llm_api_key='', llm_model='', llm_base_url='')
            self.assertEqual(config.llm_api_key, 'llm-key')

    def test_anthropic_api_key_fallback_works(self):
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'anth-key'}, clear=True):
            config = AgentConfig(llm_provider='', llm_api_key='', llm_model='', llm_base_url='')
            self.assertEqual(config.llm_provider, 'anthropic')
            self.assertEqual(config.llm_api_key, 'anth-key')
            self.assertTrue(config.llm_enabled)


class FactoryTests(unittest.TestCase):
    def test_create_llm_maps_supported_providers(self):
        with patch('agent.llm.anthropic_client.AnthropicLLM.__init__', return_value=None), patch(
            'agent.llm.openai_client.OpenAICompatibleLLM.__init__', return_value=None
        ):
            self.assertIsInstance(create_llm(provider='anthropic', api_key='k', model='m'), AnthropicLLM)
            self.assertIsInstance(create_llm(provider='openai', api_key='k', model='m'), OpenAICompatibleLLM)
            self.assertIsInstance(create_llm(provider='deepseek', api_key='k', model='m'), OpenAICompatibleLLM)
            self.assertIsInstance(
                create_llm(provider='openai-compatible', api_key='k', model='m'),
                OpenAICompatibleLLM,
            )

    def test_create_llm_rejects_unknown_provider(self):
        with self.assertRaises(ValueError):
            create_llm(provider='unknown', api_key='k', model='m')


class OpenAIParsingTests(unittest.TestCase):
    def test_invalid_tool_arguments_raise(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason='tool_calls',
                    message=SimpleNamespace(
                        content='',
                        tool_calls=[
                            SimpleNamespace(
                                id='call_1',
                                function=SimpleNamespace(name='read_file', arguments='{bad json'),
                            )
                        ],
                    ),
                )
            ]
        )
        llm = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
        with self.assertRaises(ValueError):
            llm._parse_response(response)


class StopReasonNormalizationTests(unittest.TestCase):
    def test_anthropic_stop_reason_normalization(self):
        llm = AnthropicLLM.__new__(AnthropicLLM)
        response = SimpleNamespace(
            stop_reason='tool_use',
            content=[SimpleNamespace(type='text', text='ok')],
        )
        parsed = llm._parse_response(response)
        self.assertEqual(parsed.stop_reason, 'tool_use')

    def test_openai_stop_reason_normalization(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason='length', message=SimpleNamespace(content='done', tool_calls=[]))]
        )
        llm = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
        parsed = llm._parse_response(response)
        self.assertEqual(parsed.stop_reason, 'max_tokens')


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


if __name__ == '__main__':
    unittest.main()
