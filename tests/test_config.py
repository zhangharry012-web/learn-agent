import os
import tempfile
import unittest
from pathlib import Path

from agent.config import (
    AgentConfig,
    DEFAULT_LLM_MAX_TOKENS,
    FALLBACK_LLM_MAX_TOKENS,
    _load_env_file,
)


class ConfigTests(unittest.TestCase):
    def test_load_env_file_parses_plain_lines(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            env_path = root / '.env'
            env_path.write_text('A=1\n# ignored\nB = two\n', encoding='utf-8')
            previous = Path.cwd()
            try:
                os.chdir(root)
                values = _load_env_file()
            finally:
                os.chdir(previous)
            self.assertEqual(values['A'], '1')
            self.assertEqual(values['B'], 'two')

    def test_defaults_are_loaded_when_env_file_is_missing(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            previous = Path.cwd()
            try:
                os.chdir(root)
                config = AgentConfig()
            finally:
                os.chdir(previous)
            self.assertEqual(config.llm_provider, 'anthropic')
            self.assertEqual(config.llm_model, 'claude-sonnet-4-20250514')
            self.assertEqual(config.llm_max_tokens, DEFAULT_LLM_MAX_TOKENS)
            self.assertEqual(config.llm_fallback_max_tokens, FALLBACK_LLM_MAX_TOKENS)
            self.assertEqual(config.exception_log_dir, 'logs/exceptions')
            self.assertTrue(config.observability_enabled)
            self.assertEqual(config.observability_log_dir, 'logs/observability')
            self.assertEqual(config.observability_preview_chars, 2000)
            self.assertEqual(config.observability_retention_hours, 720)

    def test_env_file_values_are_used(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            (root / '.env').write_text(
                'LLM_PROVIDER=deepseek\nLLM_API_KEY=key\nLLM_MODEL=model-x\nLLM_BASE_URL=https://example.com\n',
                encoding='utf-8',
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                config = AgentConfig()
            finally:
                os.chdir(previous)
            self.assertEqual(config.llm_provider, 'deepseek')
            self.assertEqual(config.llm_api_key, 'key')
            self.assertEqual(config.llm_model, 'model-x')
            self.assertEqual(config.llm_base_url, 'https://example.com')

    def test_anthropic_api_key_fallback_works(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            (root / '.env').write_text('ANTHROPIC_API_KEY=legacy\nANTHROPIC_MODEL=legacy-model\n', encoding='utf-8')
            previous = Path.cwd()
            try:
                os.chdir(root)
                config = AgentConfig()
            finally:
                os.chdir(previous)
            self.assertEqual(config.llm_api_key, 'legacy')
            self.assertEqual(config.llm_model, 'legacy-model')

    def test_provider_aliases_cover_supported_values(self):
        config = AgentConfig()
        self.assertIn(config.llm_provider, {'anthropic', 'openai', 'deepseek', 'openai-compatible'})

    def test_env_file_has_highest_priority(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            (root / '.env').write_text(
                'LLM_PROVIDER=openai\n'
                'LLM_MAX_TOKENS=9000\n'
                'LLM_FALLBACK_MAX_TOKENS=18000\n'
                'EXCEPTION_LOG_DIR=panic-logs\n'
                'OBSERVABILITY_ENABLED=false\n'
                'OBSERVABILITY_LOG_DIR=custom-logs\n'
                'OBSERVABILITY_PREVIEW_CHARS=128\n'
                'OBSERVABILITY_RETENTION_HOURS=48\n',
                encoding='utf-8',
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                config = AgentConfig()
            finally:
                os.chdir(previous)
            self.assertEqual(config.llm_provider, 'openai')
            self.assertEqual(config.llm_max_tokens, 9000)
            self.assertEqual(config.llm_fallback_max_tokens, 18000)
            self.assertEqual(config.exception_log_dir, 'panic-logs')
            self.assertFalse(config.observability_enabled)
            self.assertEqual(config.observability_log_dir, 'custom-logs')
            self.assertEqual(config.observability_preview_chars, 128)
            self.assertEqual(config.observability_retention_hours, 48)

    def test_invalid_retention_hours_falls_back_to_default(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            (root / '.env').write_text('OBSERVABILITY_RETENTION_HOURS=invalid\n', encoding='utf-8')
            previous = Path.cwd()
            try:
                os.chdir(root)
                config = AgentConfig()
            finally:
                os.chdir(previous)
            self.assertEqual(config.observability_retention_hours, 720)

    def test_invalid_llm_max_tokens_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            root = Path(tmpdir)
            (root / '.env').write_text(
                'LLM_MAX_TOKENS=invalid\nLLM_FALLBACK_MAX_TOKENS=bad\n',
                encoding='utf-8',
            )
            previous = Path.cwd()
            try:
                os.chdir(root)
                config = AgentConfig()
            finally:
                os.chdir(previous)
            self.assertEqual(config.llm_max_tokens, DEFAULT_LLM_MAX_TOKENS)
            self.assertEqual(config.llm_fallback_max_tokens, FALLBACK_LLM_MAX_TOKENS)
