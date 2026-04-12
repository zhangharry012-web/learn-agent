# Observability Expansion Research

## Scope

This research covers how `learn-agent` currently executes LLM turns, tool calls, shell fallback commands, and approvals, and what structural changes are needed to add practical observability.

The requested goal is to increase system observability so a human can inspect dedicated log files and understand at least:

- LLM call inputs and outputs
- system processing results
- execution duration
- token usage
- related runtime context that helps explain what happened

The solution should fit the current small codebase, preserve the existing runtime architecture, and remain easy to inspect locally.

## Current runtime behavior in detail

### Entry flow

The CLI entrypoint in `agent/cli.py` is intentionally thin. It:

1. creates `Agent()`
2. reads terminal input
3. calls `agent.handle(command)`
4. prints the returned `AgentResponse`

So the real orchestration and the best observability insertion point is not the CLI. It is the runtime layer inside `agent/runtime/agent.py`.

### `Agent` orchestration hotspots

`agent/runtime/agent.py` currently owns all major state transitions:

- config creation
- shell runner creation
- tool registry construction
- optional LLM construction
- history storage
- pending approval storage
- built-in command handling
- shell fallback execution when no LLM is configured
- LLM loop execution
- approval continuation logic

This means observability can be added without large cross-cutting rewrites if the runtime gets a small logging collaborator.

Important current transitions:

#### `handle(...)`

This method routes between:

- approval continuation
- built-ins (`help`, `exit`, `quit`)
- LLM-backed mode
- direct shell fallback mode

Today none of those branches emit persistent execution logs.

#### `_handle_shell_turn(...)`

This path:

1. checks command policy
2. possibly blocks the command
3. otherwise executes `self.shell_runner.run(command)`
4. returns `AgentResponse`

This is one clear place to log system-level execution outcome and duration even when no LLM is configured.

#### `_handle_approval(...)`

This path:

1. restores the pending tool call state
2. either executes the tool or emits a denial result
3. constructs a tool-result message
4. resumes the LLM loop

This is a critical observability point because it records whether the human approved or denied a tool action and what happened next.

#### `_run_llm_loop(...)`

This is the main LLM orchestration loop. It:

1. calls `self.llm.generate(...)`
2. converts the result to an assistant message
3. branches on tool calls vs terminal text
4. executes non-approval tool calls immediately
5. pauses if approval is needed
6. appends tool results back into the conversation
7. repeats until completion or step limit exceeded

This is the single most important place for LLM observability because it contains both:

- the LLM request/response boundary
- the runtime processing that follows the LLM response

## What is currently missing

The project currently lacks an observability layer entirely.

There is no:

- dedicated log directory
- structured event logger
- persistent trace of user commands
- persistent trace of LLM request/response metadata
- timing capture for runtime stages
- token usage capture
- record of tool approvals/denials
- record of shell fallback execution beyond transient CLI output

The architecture document even lists execution logging as a future improvement, so this request matches an already-recognized gap.

## LLM integration details relevant to observability

### Common client abstraction

`agent/llm/base.py` defines `BaseLLMClient.generate(...)` returning an `LLMResponse`.

Today `LLMResponse` only includes:

- `text`
- `tool_calls`
- `stop_reason`

This is not enough to capture token usage or provider metadata. If the runtime should log token consumption generically, the response model likely needs to grow.

### Provider response parsing

#### Anthropic

`agent/llm/anthropic_client.py` already has access to the raw SDK response object inside `_parse_response(...)`.

Anthropic responses typically expose usage information such as input/output token counts. The current parser ignores that information entirely.

#### OpenAI-compatible

`agent/llm/openai_client.py` also has access to the raw completion response object inside `_parse_response(...)`.

OpenAI-style responses typically expose `usage` data. The current parser also ignores that information entirely.

Conclusion: token observability should not be inferred in the runtime. It should be extracted in each provider parser and normalized into shared response metadata.

## Best structural landing zone for observability

### A dedicated runtime observability module is the best fit

Adding ad-hoc `print(...)` calls or open-coded JSON append logic directly in `agent/runtime/agent.py` would quickly make the runtime noisy and harder to evolve.

The best fit is a small dedicated package or module under `agent/runtime/`, for example:

- `agent/runtime/observability.py`
- or split further into `logging.py` plus `events.py`

Given current project scale, a single dedicated module is likely enough.

That module can own:

- log directory creation
- event schema helpers
- JSON-lines file writing
- timestamp generation
- sanitization/truncation policy for human-readable inspection

Then `Agent` can emit events at key boundaries without embedding file I/O details everywhere.

## What should be logged

The request says "包括但不限于" LLM 调用和系统处理结果、执行时长、消耗 token 数等, so the design should log a useful minimum set.

A practical event model for this project should include at least these event families:

### 1. Session command events

Triggered when `Agent.handle(...)` starts and ends processing a top-level user command.

Useful fields:

- timestamp
- event type
- original command
- mode (`llm`, `shell_fallback`, `built_in`, `approval_response`)
- overall success
- overall duration_ms
- response summary

### 2. LLM call events

Triggered around every `self.llm.generate(...)` call.

Useful fields:

- timestamp
- provider
- model
- system prompt summary or full prompt
- messages count
- tool definitions count
- duration_ms
- stop_reason
- output text summary
- tool call summary
- token usage

### 3. Tool execution events

Triggered whenever a tool executes or is denied.

Useful fields:

- tool name
- tool input
- whether approval was required
- whether it was approved or denied
- duration_ms if executed
- success/failure
- result summary

### 4. Shell fallback events

Triggered when no LLM is configured and the system runs a direct shell command.

Useful fields:

- command
- cwd
- duration_ms
- returncode
- stdout/stderr summary

### 5. Runtime error or loop-limit events

Triggered when:

- provider parsing fails
- tool name lookup fails
- tool execution throws
- maximum LLM step limit is exceeded

These are exactly the moments that make postmortem inspection valuable.

## Log format choice

### JSONL is the best primary format

For this codebase, JSON Lines in a dedicated log directory is the best fit because it is:

- append-friendly
- easy to inspect manually line by line
- easy to grep
- easy to parse later for summaries
- trivial to produce with the standard library

A practical directory layout could be:

```text
logs/
└── observability/
    ├── events.jsonl
    └── sessions/
        └── <session-id>.jsonl   # optional future refinement
```

For the current scope, one rolling `events.jsonl` inside a dedicated directory is enough.

### Human readability vs payload size

The user explicitly wants logs to be easy for humans to inspect. That means the system should not dump massive full message histories unboundedly into every event.

A good compromise is:

- store structured fields
- include compact previews of large text fields
- include counts and summaries for collections
- include full tool inputs for local tools because they are usually small
- truncate very long model outputs/stdout/stderr beyond a safe threshold

This keeps the logs readable while still useful.

## Dedicated log directory behavior

The requirement asks for a dedicated log folder. The natural default is something like:

- `logs/observability/`

The logger should ensure the directory exists before writing.

Potential useful files:

- `events.jsonl`: append-only structured event stream
- `README.md` is not necessary for this feature

No external logging dependency is required.

## Configuration impact

`agent/config.py` currently has no observability settings.

At minimum, the feature needs defaults for:

- whether observability is enabled
- log directory path
- maybe preview truncation limit

A practical initial config extension would add fields such as:

- `observability_enabled: bool = True`
- `observability_log_dir: str = 'logs/observability'`
- `observability_preview_chars: int = 2000`

Those can default locally without needing `.env` changes immediately, but `.env`-based overrides would keep the design extensible.

## Shared metadata model needed for token usage

Because token data originates in provider responses, `agent/llm/types.py` is the right place to define shared usage data.

A good normalized structure is something like:

- `TokenUsage`
  - `input_tokens`
  - `output_tokens`
  - `total_tokens`

and possibly an `LLMResponseMeta` or direct field on `LLMResponse`.

At current scale, embedding optional metadata directly into `LLMResponse` is simpler than introducing too many nested types, but a small dedicated `TokenUsage` dataclass would improve clarity.

## Existing tests that will be affected

### `tests/helpers.py`

`FakeLLM` currently only records calls and returns prepared `LLMResponse` objects. It can be extended to return LLM responses containing usage metadata without difficulty.

### `tests/test_agent_runtime.py`

This is the main place to validate that:

- log files are created
- LLM calls are logged
- approval outcomes are logged
- shell fallback execution is logged

### `tests/test_llm_openai.py` and `tests/test_llm_anthropic.py`

These are the correct places to assert usage parsing from provider responses.

### `tests/test_config.py`

This should expand if config gains observability defaults or env overrides.

## Recommended implementation direction

### 1. Add normalized usage metadata to `LLMResponse`

Provider parsers should populate token usage when the SDK response exposes it.

### 2. Add a dedicated runtime observability logger

This logger should:

- create the log directory lazily or at initialization
- append JSONL events
- expose small helper methods for common event types
- apply truncation helpers for large text fields

### 3. Inject the logger into `Agent`

`Agent` can create a default logger from config, similar to shell runner and policy creation.

### 4. Log at runtime boundaries, not deep everywhere

Good boundaries are:

- start/end of `handle(...)`
- before/after `llm.generate(...)`
- approval requested / approved / denied
- tool executed
- shell fallback executed
- loop limit exceeded

This keeps instrumentation meaningful rather than noisy.

### 5. Update README to mention the dedicated observability directory

The feature is user-visible operationally, so the README should mention:

- logs are written under the dedicated folder
- what kinds of events are captured

## Risks and edge cases

1. **Overlogging sensitive content**: full prompts, file contents, stdout, and stderr may be large or sensitive. The logger should prefer bounded previews over unbounded dumps.
2. **Runtime fragility from logging failures**: observability must never break core execution. Logging should fail closed and avoid raising into the main flow.
3. **Provider metadata variability**: token usage fields differ between SDKs. Normalization logic must tolerate missing usage data.
4. **Test brittleness around timestamps/durations**: tests should assert the presence of events and key fields, not exact timestamps.
5. **File growth**: a single append-only file can grow large over time, but that is acceptable for this small local project's first observability iteration.

## Recommended scope for the next plan

The next plan should cover:

- introducing a dedicated runtime observability module and JSONL event writer
- extending config with observability defaults
- extending `LLMResponse` to carry normalized token usage metadata
- parsing usage metadata in Anthropic and OpenAI-compatible clients
- instrumenting `Agent` around command handling, LLM calls, approval flow, tool execution, shell fallback, and loop-limit failures
- adding tests for provider usage parsing and log file creation/content
- updating README to document the dedicated log directory and what it contains
