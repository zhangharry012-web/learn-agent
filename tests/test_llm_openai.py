import unittest
from types import SimpleNamespace

from agent.llm.openai_client import OpenAICompatibleLLM


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

    def test_openai_stop_reason_normalization(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason='length', message=SimpleNamespace(content='done', tool_calls=[]))]
        )
        llm = OpenAICompatibleLLM.__new__(OpenAICompatibleLLM)
        parsed = llm._parse_response(response)
        self.assertEqual(parsed.stop_reason, 'max_tokens')
