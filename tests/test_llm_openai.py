import unittest
from types import SimpleNamespace

from agent.llm.openai_client import OpenAICompatibleLLM
from agent.llm.types import LLMToolCallFormatError


class OpenAIParsingTests(unittest.TestCase):
    def test_invalid_tool_arguments_raise_format_error(self):
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
        with self.assertRaises(LLMToolCallFormatError):
            llm._parse_response(response)

    def test_non_object_tool_arguments_raise_format_error(self):
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason='tool_calls',
                    message=SimpleNamespace(
                        content='',
                        tool_calls=[
                            SimpleNamespace(
                                id='call_1',
                                function=SimpleNamespace(name='read_file', arguments='[1, 2, 3]'),
                            )
                        ],
                    ),
                )
            ]
        )
        llm = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
        with self.assertRaises(LLMToolCallFormatError):
            llm._parse_response(response)

    def test_openai_stop_reason_normalization(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason='length', message=SimpleNamespace(content='done', tool_calls=[]))]
        )
        llm = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
        parsed = llm._parse_response(response)
        self.assertEqual(parsed.stop_reason, 'max_tokens')

    def test_openai_usage_is_normalized(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='done', tool_calls=[]))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
        )
        llm = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
        parsed = llm._parse_response(response)
        self.assertIsNotNone(parsed.usage)
        self.assertEqual(parsed.usage.input_tokens, 12)
        self.assertEqual(parsed.usage.output_tokens, 8)
        self.assertEqual(parsed.usage.total_tokens, 20)
