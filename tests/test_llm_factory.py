import unittest
from unittest.mock import patch

from agent.llm import create_llm
from agent.llm.anthropic_client import AnthropicLLM
from agent.llm.openai_client import OpenAICompatibleLLM


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
