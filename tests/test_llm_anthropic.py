import unittest
from types import SimpleNamespace

from agent.llm.anthropic_client import AnthropicLLM


class StopReasonNormalizationTests(unittest.TestCase):
    def test_anthropic_stop_reason_normalization(self):
        llm = AnthropicLLM.__new__(AnthropicLLM)
        response = SimpleNamespace(
            stop_reason='tool_use',
            content=[SimpleNamespace(type='text', text='ok')],
        )
        parsed = llm._parse_response(response)
        self.assertEqual(parsed.stop_reason, 'tool_use')
