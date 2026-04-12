# Project Structure Refactor Plan

## Overview

This refactor will restructure the `learn-agent` codebase so that the runtime and tooling layers are organized by responsibility rather than by historical accumulation. The implementation will keep behavior stable while improving cohesion, reducing hotspot files, making future additions more additive, and keeping most files under the 200–300 line target.

The main changes will be:

- convert `agent/tools.py` into a `agent/tools/` package
- split `agent/core.py` into smaller runtime-focused modules
- split `tests/test_agent.py` into subsystem-oriented test modules
- preserve the current external behavior and configuration model

## Target file structure

```text
learn-agent/
├── agent/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── core.py                    # compatibility export or thin facade
│   ├── policy.py
│   ├── shell.py
│   ├── runtime/
│   │   ├── __init__.py
│   │   ├── agent.py               # public Agent implementation
│   │   ├── types.py               # AgentResponse, PendingApproval
│   │   ├── loop.py                # llm tool loop orchestration helpers
│   │   └── messages.py            # assistant/tool-result message builders + system prompt
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py                # BaseTool and shared path helpers
│   │   ├── types.py               # ToolExecutionResult
│   │   ├── registry.py            # build_tools and registration composition
│   │   ├── file_tools.py          # ReadFileTool, WriteFileTool
│   │   └── git_tool.py            # GitTool
│   └── llm/
│       ├── __init__.py
│       ├── anthropic_client.py
│       ├── base.py
│       ├── openai_client.py
│       └── types.py
├── tests/
│   ├── test_agent_runtime.py
│   ├── test_config.py
│   ├── test_policy.py
│   ├── test_tools.py
│   ├── test_llm_factory.py
│   ├── test_llm_openai.py
│   └── test_llm_anthropic.py
├── main.py
├── README.md
└── docs/project-structure-refactor/
    ├── research.md
    └── plan.md
```

## Architecture diagram

```text
User Input
   |
   v
agent.cli
   |
   v
agent.core  (thin facade / compatibility layer)
   |
   v
agent.runtime.agent.Agent
   |------------------------------|
   |                              |
   v                              v
agent.policy                 agent.llm.create_llm(...)
   |                              |
   |                              v
   |                       Provider-specific clients
   |                       (anthropic/openai-compatible)
   |
   v
Shell fallback

For tool-enabled LLM turns:

agent.runtime.agent.Agent
   |
   v
agent.runtime.loop helpers
   |
   v
agent.tools.registry.build_tools(...)
   |
   |-----------------------------|
   |                             |
   v                             v
agent.tools.file_tools     agent.tools.git_tool
   |
   v
ToolExecutionResult -> runtime message builders -> llm next turn
```

## Module design

### `agent/core.py`

Role: preserve the current import entrypoint and avoid unnecessary churn.

Planned shape:

- either re-export `Agent`, `AgentResponse`, and `PendingApproval` from the new runtime package
- or act as a very small facade module that imports from `agent.runtime`

Why:

- keeps current import sites stable
- avoids forcing unrelated changes in CLI/tests/docs beyond what is necessary

### `agent/runtime/types.py`

Responsibilities:

- define `AgentResponse`
- define `PendingApproval`

Why:

- these are pure runtime state/data definitions
- separating them keeps the main runtime implementation shorter and makes type contracts easier to locate

Key interface:

```python
@dataclass
class AgentResponse: ...

@dataclass
class PendingApproval: ...
```

### `agent/runtime/messages.py`

Responsibilities:

- build assistant messages from LLM responses
- build tool-result messages from runtime tool results
- hold the system prompt text or a helper function returning it

Why:

- these are formatting/serialization concerns, not core runtime state transitions
- changes to prompt wording or message structure should not require editing the main agent class

Key interface:

```python
def build_assistant_message(text: str, tool_calls: list[Any]) -> dict[str, Any]: ...
def build_tool_result_message(tool_results: list[ToolResult]) -> dict[str, Any]: ...
def build_system_prompt() -> str: ...
```

### `agent/runtime/loop.py`

Responsibilities:

- host helpers for the iterative LLM/tool loop
- keep step-limit and loop mechanics together
- centralize logic that executes non-approval tool calls and collects `ToolResult`

Why:

- the looping behavior is the most complex part of the runtime
- isolating it reduces `Agent` class size and gives future extensions a dedicated home

Important note:

- the public `Agent.handle(...)` flow should remain easy to read; `loop.py` should support that rather than obscuring it

Possible helper shape:

```python
def run_llm_loop(agent: Agent, messages: list[dict[str, Any]], original_command: str) -> AgentResponse: ...
```

or a smaller helper set if passing the whole `Agent` object feels too implicit.

Preferred direction:

- keep it simple and explicit
- if helper functions need too many parameters, place the logic as internal methods on `Agent` instead and use `messages.py` + `types.py` only

This means `loop.py` is desirable but not mandatory if it makes the design worse. The implementation should optimize for clarity, not dogmatically maximize file count.

### `agent/runtime/agent.py`

Responsibilities:

- contain the public `Agent` class
- own wiring of config, shell runner, policy, llm, tool registry, history, and pending approvals
- route built-in commands
- invoke helpers from `messages.py` and runtime/tool packages

Why:

- keeps the top-level runtime object focused on orchestration
- removes pure data/model and pure formatting concerns from the same file

### `agent/tools/types.py`

Responsibilities:

- define `ToolExecutionResult`

Why:

- pure result model should not live beside concrete tool implementations

### `agent/tools/base.py`

Responsibilities:

- define `BaseTool`
- keep shared helpers such as workspace path resolution
- keep default approval prompt behavior

Why:

- stable tool contract belongs in one place
- future tools should depend on a small shared base module rather than import sibling concrete tools

Key interface contract to preserve:

```python
class BaseTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    requires_approval: bool

    def definition(self) -> dict[str, Any]: ...
    def execute(self, payload: Mapping[str, Any]) -> ToolExecutionResult: ...
    def approval_prompt(self, payload: Mapping[str, Any]) -> str: ...
```

### `agent/tools/file_tools.py`

Responsibilities:

- contain `ReadFileTool`
- contain `WriteFileTool`

Why:

- both tools operate on workspace file I/O and share the same conceptual area
- splitting by tool family is more cohesive than a file-per-class approach at this scale

### `agent/tools/git_tool.py`

Responsibilities:

- contain `GitTool`

Why:

- git operations have different dependencies and semantics from file tools
- likely future git-related helpers can live here without contaminating file tools

### `agent/tools/registry.py`

Responsibilities:

- implement `build_tools(...)`
- compose enabled tool instances
- keep registration logic separate from concrete implementations

Why:

- adding a new tool should involve editing the registry and adding a new implementation module, rather than opening a large mixed-concern file
- this keeps the registry as the one intentional composition point

Important trade-off:

- this is still an explicit registry, not dynamic plugin discovery
- explicit construction is preferred here because the project is small and clarity matters more than framework flexibility

### `agent/tools/__init__.py`

Responsibilities:

- expose the public tool API
- optionally provide compatibility re-exports so existing imports still work

Likely exports:

- `BaseTool`
- `ToolExecutionResult`
- `ReadFileTool`
- `WriteFileTool`
- `GitTool`
- `build_tools`

### Test modules

Responsibilities:

- mirror production subsystem boundaries
- keep each test file focused and smaller

Planned mapping:

| Current test area | New file |
|---|---|
| Command policy tests | `tests/test_policy.py` |
| Tool tests | `tests/test_tools.py` |
| Config tests | `tests/test_config.py` |
| Factory tests | `tests/test_llm_factory.py` |
| OpenAI parsing tests | `tests/test_llm_openai.py` |
| Anthropic normalization tests | `tests/test_llm_anthropic.py` |
| Agent approval/runtime tests | `tests/test_agent_runtime.py` |

## Design decisions

### 1. Prefer package extraction over introducing a plugin framework

Decision:

- split into packages/modules, but keep registration explicit

Why:

- satisfies cohesion and extensibility goals without over-engineering
- easier to debug and read in a small repo

Rejected alternative:

- auto-discover tools/providers dynamically

Reason rejected:

- unnecessary complexity for current scale
- adds indirection without real present value

### 2. Preserve public import ergonomics where practical

Decision:

- keep `agent.core` and `agent.tools` as importable public surfaces via facades/re-exports

Why:

- reduces churn
- makes the refactor safer
- helps tests and docs migrate gradually

Rejected alternative:

- force all call sites to import from deep new module paths immediately

Reason rejected:

- little value, more churn

### 3. Split by responsibility, not only by line count

Decision:

- use domain-based module boundaries (`runtime`, `tools`) rather than arbitrary slicing

Why:

- improves maintainability beyond just reducing file size
- aligns better with open-closed goals

### 4. Keep behavior stable during the refactor

Decision:

- this refactor should not change approval rules, shell fallback semantics, provider behavior, or `.env` precedence

Why:

- users requested a structural optimization, not a behavioral redesign
- smaller blast radius makes validation easier

## Dependencies

No new runtime dependencies are planned.

This should remain a pure structural refactor using the existing standard library and current third-party packages.

## Usage / configuration impact

End-user behavior should remain unchanged.

Expected unchanged behavior:

- CLI usage remains the same
- `.env` setup remains the same
- provider selection remains the same
- approval prompts for `write_file` and `git_run` remain the same
- shell fallback when no LLM is configured remains the same

The visible impact should mainly be improved internal maintainability.

## What stays unchanged

Unless needed for import updates or minor cleanup, the following should remain behaviorally unchanged:

- `agent/cli.py`
- `agent/config.py`
- `agent/policy.py`
- `agent/shell.py`
- `agent/llm/base.py`
- `agent/llm/types.py`
- `agent/llm/anthropic_client.py`
- `agent/llm/openai_client.py`
- `.env` semantics
- provider alias semantics

## Extensibility after the refactor

### Adding a new tool

Target path after refactor:

1. create a new module in `agent/tools/` or extend the relevant tool-family module
2. implement `BaseTool`
3. add one explicit registration line in `agent/tools/registry.py`
4. add focused tests in `tests/test_tools.py` or a dedicated tool test module if needed

This is more additive and localized than editing one large shared `tools.py` file.

### Adding runtime behavior

If future work introduces richer approval strategies, command routing, or session state, there will be clearer landing zones:

- runtime data -> `agent/runtime/types.py`
- runtime message formatting -> `agent/runtime/messages.py`
- runtime orchestration -> `agent/runtime/agent.py` or `loop.py`

### Adding a new LLM provider

This should continue using the existing `agent/llm/` pattern, which is already aligned with the desired design style.

## Migration strategy

Implementation should proceed in small safe steps:

1. create new packages/modules first
2. move shared types/contracts
3. move tool implementations and preserve exports
4. move runtime models/helpers and preserve `agent.core` import surface
5. split tests and keep coverage green throughout
6. update README structure section only if it currently references old file layout in a way that becomes inaccurate

This order minimizes breakage and keeps each step verifiable.

## Validation strategy

The refactor is successful if all of the following are true:

1. tests still pass
2. public behavior is unchanged
3. imports remain clean and unsurprising
4. `agent/tools.py` no longer contains the concrete tool implementations as a monolith
5. `agent/core.py` is reduced to a thin facade or otherwise falls comfortably within the size target
6. tests are split by subsystem rather than concentrated in a single file
7. no new dependency or framework complexity is introduced

## TODO

- [ ] Create `agent/tools/` package and shared modules (`base.py`, `types.py`, `registry.py`)
- [ ] Move `ReadFileTool` and `WriteFileTool` into `agent/tools/file_tools.py`
- [ ] Move `GitTool` into `agent/tools/git_tool.py`
- [ ] Add `agent/tools/__init__.py` re-exports and preserve current import ergonomics
- [ ] Introduce `agent/runtime/` package for runtime models/helpers
- [ ] Move `AgentResponse` and `PendingApproval` into `agent/runtime/types.py`
- [ ] Extract runtime message builders/system prompt into `agent/runtime/messages.py`
- [ ] Reduce `agent/core.py` to a thin facade or slimmer orchestration module
- [ ] Update imports across production code to the new module layout
- [ ] Split `tests/test_agent.py` into subsystem-oriented test modules
- [ ] Run the full test suite and verify no behavior changes
- [ ] Update README only where structure descriptions become outdated
- [ ] Review final file sizes to ensure the refactor meets the 200–300 line target in practice
