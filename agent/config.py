from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, Mapping, Tuple

DEFAULT_PROVIDER = 'anthropic'
DEFAULT_MODEL = 'claude-sonnet-4-20250514'
DEFAULT_LLM_MAX_TOKENS = 8 * 1024
FALLBACK_LLM_MAX_TOKENS = 16 * 1024
DEFAULT_MAX_TOOL_STEPS = 25
DEFAULT_VERIFY_TIMEOUT_SEC = 120
ENV_FILE_NAME = '.env'
SUPPORTED_OPENAI_COMPATIBLE_PROVIDERS: FrozenSet[str] = frozenset(
    {'openai', 'deepseek', 'openai-compatible'}
)


def _load_env_file() -> Dict[str, str]:
    env_path = Path.cwd() / ENV_FILE_NAME
    if not env_path.exists():
        return {}

    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def _get_env_value(key: str, default: str = '') -> str:
    env_file_values = _load_env_file()
    return env_file_values.get(key, default)


def _get_env_bool(key: str, default: bool) -> bool:
    raw = _get_env_value(key)
    if not raw:
        return default
    return raw.lower() in {'1', 'true', 'yes', 'on'}


def _get_env_int(key: str, default: int) -> int:
    raw = _get_env_value(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class AgentConfig:
    llm_provider: str = field(default_factory=lambda: _get_env_value('LLM_PROVIDER', DEFAULT_PROVIDER))
    llm_api_key: str = field(
        default_factory=lambda: _get_env_value('LLM_API_KEY') or _get_env_value('ANTHROPIC_API_KEY')
    )
    llm_model: str = field(
        default_factory=lambda: _get_env_value('LLM_MODEL') or _get_env_value('ANTHROPIC_MODEL', DEFAULT_MODEL)
    )
    llm_base_url: str = field(default_factory=lambda: _get_env_value('LLM_BASE_URL'))
    llm_max_tokens: int = field(
        default_factory=lambda: _get_env_int('LLM_MAX_TOKENS', DEFAULT_LLM_MAX_TOKENS)
    )
    llm_fallback_max_tokens: int = field(
        default_factory=lambda: _get_env_int('LLM_FALLBACK_MAX_TOKENS', FALLBACK_LLM_MAX_TOKENS)
    )
    enabled_tools: Tuple[str, ...] = (
        'read_file',
        'write_file',
        'edit_file',

        'exec',
        'inspect_path',
        'read_only_command',
        'verify_command',
    )
    observability_enabled: bool = field(default_factory=lambda: _get_env_bool('OBSERVABILITY_ENABLED', True))
    observability_log_dir: str = field(
        default_factory=lambda: _get_env_value('OBSERVABILITY_LOG_DIR', 'logs/observability')
    )
    observability_preview_chars: int = field(
        default_factory=lambda: _get_env_int('OBSERVABILITY_PREVIEW_CHARS', 2000)
    )
    observability_retention_hours: int = field(
        default_factory=lambda: _get_env_int('OBSERVABILITY_RETENTION_HOURS', 24 * 30)
    )
    exception_log_dir: str = field(
        default_factory=lambda: _get_env_value('EXCEPTION_LOG_DIR', 'logs/exceptions')
    )
    verify_auto_approve_enabled: bool = field(
        default_factory=lambda: _get_env_bool('VERIFY_AUTO_APPROVE_ENABLED', True)
    )
    verify_policy_file: str = field(
        default_factory=lambda: _get_env_value('VERIFY_POLICY_FILE', '.agent/verify-policy.json')
    )
    verify_default_timeout_sec: int = field(
        default_factory=lambda: _get_env_int('VERIFY_DEFAULT_TIMEOUT_SEC', DEFAULT_VERIFY_TIMEOUT_SEC)
    )
    verify_require_repo_policy: bool = field(
        default_factory=lambda: _get_env_bool('VERIFY_REQUIRE_REPO_POLICY', False)
    )
    llm_max_tool_steps: int = field(
        default_factory=lambda: _get_env_int('LLM_MAX_TOOL_STEPS', DEFAULT_MAX_TOOL_STEPS)
    )

    @property
    def anthropic_api_key(self) -> str:
        return self.llm_api_key

    @property
    def anthropic_model(self) -> str:
        return self.llm_model

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


PROVIDER_CLASS_ALIASES: Mapping[str, str] = {
    DEFAULT_PROVIDER: 'anthropic',
    'openai': 'openai-compatible',
    'deepseek': 'openai-compatible',
    'openai-compatible': 'openai-compatible',
}
