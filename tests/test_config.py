import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    PROVIDER_CLASS_ALIASES,
    AgentConfig,
)


class ConfigTests(unittest.TestCase):
    def test_defaults_are_loaded_when_env_file_is_missing(self):
        with patch('agent.config._load_env_file', return_value={}):
            config = AgentConfig()
            self.assertEqual(config.llm_provider, DEFAULT_PROVIDER)
            self.assertEqual(config.llm_model, DEFAULT_MODEL)
            self.assertEqual(config.llm_api_key, '')
            self.assertEqual(config.llm_base_url, '')

    def test_env_file_values_are_used(self):
        fake_values = {
            'LLM_PROVIDER': 'deepseek',
            'LLM_API_KEY': 'env-key',
            'LLM_MODEL': 'deepseek-chat',
            'LLM_BASE_URL': 'https://api.deepseek.com',
        }
        with patch('agent.config._load_env_file', return_value=fake_values):
            config = AgentConfig()
            self.assertEqual(config.llm_provider, 'deepseek')
            self.assertEqual(config.llm_api_key, 'env-key')
            self.assertEqual(config.llm_model, 'deepseek-chat')
            self.assertEqual(config.llm_base_url, 'https://api.deepseek.com')

    def test_anthropic_api_key_fallback_works(self):
        fake_values = {'ANTHROPIC_API_KEY': 'anth-key'}
        with patch('agent.config._load_env_file', return_value=fake_values):
            config = AgentConfig()
            self.assertEqual(config.llm_provider, DEFAULT_PROVIDER)
            self.assertEqual(config.llm_api_key, 'anth-key')
            self.assertTrue(config.llm_enabled)

    def test_env_file_has_highest_priority(self):
        fake_values = {
            'LLM_API_KEY': 'env-file-key',
            'ANTHROPIC_API_KEY': 'anth-file-key',
        }
        with patch('agent.config._load_env_file', return_value=fake_values):
            config = AgentConfig()
            self.assertEqual(config.llm_api_key, 'env-file-key')

    def test_load_env_file_parses_plain_lines(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            env_file = root / '.env'
            env_file.write_text(
                '# comment\nLLM_PROVIDER=openai\nLLM_API_KEY=test-key\nLLM_BASE_URL="https://example.com"\n',
                encoding='utf-8',
            )
            with patch('agent.config.Path.cwd', return_value=root):
                from agent import config as config_module
                values = config_module._load_env_file()
            self.assertEqual(values['LLM_PROVIDER'], 'openai')
            self.assertEqual(values['LLM_API_KEY'], 'test-key')
            self.assertEqual(values['LLM_BASE_URL'], 'https://example.com')

    def test_provider_aliases_cover_supported_values(self):
        self.assertEqual(PROVIDER_CLASS_ALIASES[DEFAULT_PROVIDER], 'anthropic')
        self.assertEqual(PROVIDER_CLASS_ALIASES['openai'], 'openai-compatible')
        self.assertEqual(PROVIDER_CLASS_ALIASES['deepseek'], 'openai-compatible')
        self.assertEqual(PROVIDER_CLASS_ALIASES['openai-compatible'], 'openai-compatible')
