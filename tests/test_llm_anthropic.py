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

    def test_anthropic_usage_is_normalized(self):
        llm = AnthropicLLM.__new__(AnthropicLLM)
        response = SimpleNamespace(
            stop_reason='end_turn',
            content=[SimpleNamespace(type='text', text='ok')],
            usage=SimpleNamespace(input_tokens=11, output_tokens=7),
        )
        parsed = llm._parse_response(response)
        self.assertIsNotNone(parsed.usage)
        self.assertEqual(parsed.usage.input_tokens, 11)
        self.assertEqual(parsed.usage.output_tokens, 7)
        self.assertEqual(parsed.usage.total_tokens, 18)
