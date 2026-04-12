## Summary

This PR adds multi-provider LLM support to `learn-agent` by extracting the previous single-provider `agent/llm.py` implementation into a provider-based package, introducing a unified internal LLM response/message model, and adding OpenAI-compatible provider support with `base_url` configuration.

It also switches runtime configuration loading to the project root `.env` file, adds `.env.example`, documents the new setup flow, and ensures `.env` is ignored by Git. `.env` values now have the highest priority because runtime configuration is loaded directly from that file.

## What changed

### 1. Split `agent/llm.py` into a provider package

Replaced the old single-file Anthropic-only implementation with:

- `agent/llm/types.py`
- `agent/llm/base.py`
- `agent/llm/anthropic_client.py`
- `agent/llm/openai_client.py`
- `agent/llm/__init__.py`

This introduces a cleaner separation between:

- shared abstractions
- provider-specific message/tool conversion
- client factory wiring

### 2. Added unified internal LLM types

Introduced shared internal types:

- `ToolCall`
- `ToolResult`
- `LLMResponse`

`core.py` now consumes these provider-agnostic types instead of raw Anthropic response blocks.

### 3. Added OpenAI-compatible provider support

Added `OpenAICompatibleLLM` with support for:

- OpenAI-compatible chat completions APIs
- tool call translation
- tool argument JSON parsing
- configurable `base_url`

This enables DeepSeek and other OpenAI-compatible backends via configuration.

### 4. Switched config loading to `.env`

`AgentConfig` now reads runtime configuration from the project root `.env` file.

Supported keys include:

- `LLM_PROVIDER`
- `LLM_API_KEY`
- `LLM_MODEL`
- `LLM_BASE_URL`
- `ANTHROPIC_API_KEY`
- `ANTHROPIC_MODEL`

Behavior notes:

- `.env` is now the runtime configuration source
- `.env` values have the highest priority
- backward-compatible Anthropic aliases are still supported inside `.env`
- `.env.example` is provided as the onboarding template
- `.env` is ignored by Git and is not committed

### 5. Refactored agent loop to use unified message flow

Updated `agent/core.py` so the main loop:

- builds provider-independent assistant messages
- stores tool results in a unified structure
- routes client construction through `create_llm()`
- keeps approval-gated tool execution behavior unchanged

### 6. Updated CLI behavior

CLI startup output is now provider-neutral and shows:

- configured provider
- configured model
- whether `base_url` is set

### 7. Updated documentation

Updated `README.md` to reflect:

- `.env`-based setup
- `.env.example` usage
- multi-provider configuration examples
- current project structure and docs links

### 8. Added test coverage

Expanded tests to cover:

- `.env` parsing behavior
- config defaults when `.env` is missing
- Anthropic fallback aliases inside `.env`
- provider factory mapping
- unsupported provider rejection
- stop reason normalization
- invalid OpenAI tool argument handling
- existing approval flow regression behavior

### 9. Cleanup

- Added `openai>=1.0.0` to `requirements.txt`
- Added `.gitignore` rules for Python cache files and `.env`
- Removed tracked `__pycache__` / `.pyc` artifacts from the repo

## Compatibility / behavior notes

- Default provider remains `anthropic`
- Existing Anthropic naming is still supported via `.env` aliases
- OpenAI-compatible providers require explicit `LLM_PROVIDER`, `LLM_API_KEY`, and usually `LLM_BASE_URL`
- `base_url` is passed through as-is; no automatic normalization is performed
- `.env` is the intended local runtime configuration path going forward

## Example configuration

### Anthropic

```bash
cp .env.example .env
```

```bash
LLM_PROVIDER=anthropic
LLM_API_KEY=your_api_key
LLM_MODEL=claude-sonnet-4-20250514
```

### DeepSeek

```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=your_api_key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
```

### Anthropic alias style inside `.env`

```bash
ANTHROPIC_API_KEY=your_api_key
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

## Validation

- Updated unit tests
- Ran test suite after config changes
- Verified `.env` is ignored by Git
- Verified cache artifacts are no longer tracked

## Related docs

- `docs/multi-llm-provider/research.md`
- `docs/multi-llm-provider/plan.md`
