# Observability Expansion Plan

## Overview

This change will add a lightweight observability layer to `learn-agent` so every important runtime step can be inspected from a dedicated local log directory. The system will persist structured JSONL events for top-level command handling, LLM calls, tool approvals/executions, shell fallback execution, and loop-limit/error cases, including duration and normalized token usage where available.

The implementation will preserve the current architecture by introducing a focused runtime observability module, extending the shared LLM response model with optional usage metadata, and instrumenting the existing `Agent` orchestration boundaries rather than scattering logging logic across unrelated modules.

## Target file structure

```text
learn-agent/
├── README.md                              # document observability behavior and log directory
├── research.md                            # task-specific research artifact
├── plan.md                                # task-specific implementation plan
├── logs/
│   └── observability/                     # runtime-created dedicated log directory
│       └── events.jsonl                   # append-only structured events
├── agent/
│   ├── config.py                          # observability defaults/config
│   ├── runtime/
│   │   ├── agent.py                       # emit observability events at runtime boundaries
│   │   ├── observability.py               # new JSONL event logger + helpers
│   │   └── types.py                       # may remain unchanged unless runtime result metadata expands
│   └── llm/
│       ├── types.py                       # normalized token usage metadata
│       ├── anthropic_client.py            # usage parsing
│       └── openai_client.py               # usage parsing
└── tests/
    ├── helpers.py                         # fake logger or richer fake LLM helpers if needed
    ├── test_agent_runtime.py              # observability log emission tests
    ├── test_llm_anthropic.py              # usage parsing tests
    ├── test_llm_openai.py                 # usage parsing tests
    └── test_config.py                     # observability defaults/env override tests
```

## Architecture diagram

```text
User Input
   |
   v
agent.cli
   |
   v
runtime.Agent.handle(...)
   |
   |------------------ command lifecycle events -------------------> runtime.observability
   |
   +--> built-in branch -------------------------------------------> runtime.observability
   |
   +--> shell fallback -> shell runner ----------------------------> runtime.observability
   |
   +--> LLM loop
         |
         +--> llm client generate(...) -> normalized usage metadata
         |          |
         |          +----------------------------------------------> runtime.observability
         |
         +--> tool approval / denial / execution ------------------> runtime.observability
         |
         +--> final response / loop-limit / error -----------------> runtime.observability
```

## Module design

### `agent/runtime/observability.py`

Introduce a dedicated runtime observability module.

Responsibilities:

- create and manage the dedicated log directory
- append JSONL events safely
- provide timestamp and duration helpers
- sanitize/truncate large payloads for human-readable logs
- never raise into the main runtime flow on logging failure

Proposed structure:

```python
class ObservabilityLogger:
    def __init__(self, log_dir: Path, enabled: bool = True, preview_chars: int = 2000) -> None: ...
    def log_event(self, event_type: str, payload: dict[str, Any]) -> None: ...
    def preview(self, value: Any) -> Any: ...
```

Expected file behavior:

- dedicated log directory defaults to `logs/observability`
- primary log file is `events.jsonl`
- each line is a single JSON object with timestamp, event type, and structured payload

Failure policy:

- if directory creation or file append fails, swallow the error
- the agent must continue functioning even when observability fails

### `agent/llm/types.py`

Extend the shared response types with normalized usage metadata.

Recommended shape:

```python
@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

@dataclass
class LLMResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    usage: TokenUsage | None = None
```

Why:

- token usage belongs to the provider response normalization layer
- runtime logging should consume normalized data rather than provider-specific fields

### `agent/llm/anthropic_client.py`

Update response parsing to populate normalized usage metadata when Anthropic returns it.

Responsibilities:

- read usage fields from the SDK response if present
- tolerate missing or partial usage data
- compute total tokens if it is not provided explicitly

### `agent/llm/openai_client.py`

Update response parsing to populate normalized usage metadata when OpenAI-compatible providers return it.

Responsibilities:

- read `response.usage` fields if present
- normalize prompt/completion/total tokens to the shared model
- tolerate missing usage data

### `agent/config.py`

Add small observability-related config defaults.

Recommended fields:

- `observability_enabled: bool = True`
- `observability_log_dir: str = 'logs/observability'`
- `observability_preview_chars: int = 2000`

Potential env keys:

- `OBSERVABILITY_ENABLED`
- `OBSERVABILITY_LOG_DIR`
- `OBSERVABILITY_PREVIEW_CHARS`

Why:

- keeps the logger configurable without complicating the user-facing workflow
- preserves local-first defaults

### `agent/runtime/agent.py`

Instrument the main runtime boundaries using the new logger.

Key integration points:

#### Agent initialization

- create `ObservabilityLogger` from config and workspace root

#### `handle(...)`

Log top-level command lifecycle events:

- command received
- command completed
- mode used (`built_in`, `approval_response`, `llm`, `shell_fallback`)
- overall duration and result summary

#### `_handle_shell_turn(...)`

Log:

- policy denial events
- shell fallback execution result
- duration, return code, stdout/stderr preview

#### `_handle_approval(...)`

Log:

- approval decision (`approved` or `denied`)
- tool identity and input preview
- tool execution result if approved
- resumed loop continuation outcome if relevant

#### `_run_llm_loop(...)`

For each LLM step log:

- request metadata: provider, model, message count, tool count
- response metadata: stop reason, text preview, tool calls summary, token usage
- LLM round-trip duration
- immediate tool execution events for non-approval tools
- approval-requested event when the runtime pauses
- final response completion event when text is returned
- loop-limit failure event if the maximum step count is exceeded

Important implementation guardrail:

- keep logging as small helper calls around existing branches; do not rewrite the loop architecture unnecessarily

### `README.md`

Update the README to document:

- the existence of the dedicated log directory
- the default log path
- what kinds of events are written there
- that token usage is recorded when the provider exposes it

## Event model

The primary event schema should stay compact and consistent.

Common top-level keys:

- `timestamp`
- `event_type`
- `session_id`
- `payload`

A lightweight session identifier generated at `Agent` initialization is useful so a human can group events from one run.

Recommended event types:

- `command_received`
- `command_completed`
- `command_blocked`
- `shell_fallback_executed`
- `llm_call_completed`
- `tool_approval_requested`
- `tool_approval_decided`
- `tool_executed`
- `llm_loop_limit_exceeded`
- `runtime_error` (optional if implementation encounters a meaningful catch boundary)

## Data handling policy

To keep logs inspectable and bounded:

- store previews instead of unbounded full payloads for long text
- include explicit preview truncation markers when shortened
- include counts for large collections
- include full scalar metadata such as provider, model, stop reason, durations, token usage, return codes, and tool names
- keep tool input logging limited to reasonably small JSON-serializable previews

This balances human readability with usefulness.

## Design decisions and trade-offs

### 1. JSONL instead of stdlib logging formatter trees

Chosen approach:

- append structured JSONL directly

Why:

- simpler to inspect locally
- easier to grep and parse
- no need for formatter/handler complexity in a small project

Trade-off:

- less feature-rich than a full logging stack
- acceptable for current scale

### 2. Dedicated runtime logger instead of inline file writes

Chosen approach:

- `agent/runtime/observability.py`

Why:

- keeps `agent/runtime/agent.py` focused on orchestration
- centralizes truncation and failure handling

Trade-off:

- one extra small module
- worth it for maintainability

### 3. Normalize token usage at provider parsing time

Chosen approach:

- parse usage in provider clients and expose it via `LLMResponse`

Why:

- runtime should not depend on provider-specific response shapes
- provider normalization is already the established abstraction boundary

Trade-off:

- small change to shared LLM response model and tests
- appropriate for cross-provider consistency

### 4. Log summaries/previews rather than unlimited payloads

Chosen approach:

- truncate large text fields to a configurable preview length

Why:

- user wants logs easy to inspect manually
- avoids runaway file growth and unreadable entries

Trade-off:

- some very long outputs will be partially logged
- acceptable because this is observability, not full archival replay

## What stays unchanged

The following should not need major redesign for this feature:

- CLI interaction contract
- tool definitions and approval semantics
- provider factory wiring in `agent/llm/__init__.py`
- core compatibility facade in `agent/core.py`
- command policy behavior

## Usage and operational behavior

Default behavior after implementation:

- logs are written automatically under `logs/observability/events.jsonl`
- every run of the agent appends structured events
- a human can inspect the file with tools like `tail`, `cat`, or `grep`

Potential examples:

```bash
tail -n 20 logs/observability/events.jsonl
grep '"event_type": "llm_call_completed"' logs/observability/events.jsonl
```

## Validation strategy

Stage 1 targeted validation:

1. provider parsing tests for token usage
2. runtime tests for log file creation and expected event types
3. config tests for observability defaults

Stage 2 full validation:

1. full `python -m unittest discover -s tests -p 'test*.py' -v`

## Extensibility after this change

This design should make future observability additions mostly additive, such as:

- separate per-session log files
- richer event taxonomies
- optional debug-level full payload logging
- lightweight aggregation utilities
- replay and trace viewers

## TODO

- [ ] Add normalized token usage metadata to `agent/llm/types.py`
- [ ] Parse token usage in `agent/llm/anthropic_client.py`
- [ ] Parse token usage in `agent/llm/openai_client.py`
- [ ] Add observability config defaults to `agent/config.py`
- [ ] Add `agent/runtime/observability.py` with safe JSONL event logging
- [ ] Instrument `agent/runtime/agent.py` for command lifecycle, LLM calls, tool events, shell fallback events, and loop-limit failures
- [ ] Update `README.md` to document observability logs and directory layout
- [ ] Add/extend tests for provider usage parsing
- [ ] Add runtime tests for observability log creation and key event capture
- [ ] Add/extend config tests for observability defaults
- [ ] Run targeted validation
- [ ] Run full test validation
- [ ] Commit and push the implementation round
