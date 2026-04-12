# Project Structure Refactor Plan

## Overview

This refactor will restructure the `learn-agent` codebase so that the runtime and tooling layers are organized by responsibility rather than by historical accumulation. The implementation will keep behavior stable while improving cohesion, reducing hotspot files, making future additions more additive, and keeping most files under the 200–300 line target.

The main changes will be:

- convert `agent/tools.py` into a `agent/tools/` package
- split `agent/core.py` into smaller runtime-focused modules
- split `tests/test_agent.py` into subsystem-oriented test modules
- preserve the current external behavior and configuration model

## What is being tightened in this revision

Compared with the previous draft, this revision strengthens five areas:

1. it clearly separates the high-priority refactor targets from modules that should remain mostly stable
2. it makes `runtime/loop.py` conditional instead of mandatory, to avoid over-fragmentation
3. it defines a practical open-closed acceptance standard for adding future tools
4. it adds explicit refactor guardrails so the implementation stays structural rather than behavioral
5. it adds migration and validation expectations around compatibility imports and file-size outcomes

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
│   │   ├── messages.py            # assistant/tool-result message builders + system prompt
│   │   └── loop.py                # optional: only if agent.py remains too dense after extraction
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
agent.runtime.messages
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

If, after extracting runtime types and message helpers, the orchestration logic in `agent.runtime.agent` is still too dense, then an additional helper module `agent.runtime.loop` can be introduced. It should not be created by default unless it clearly improves readability.

## Module design

### `agent/core.py`

Role: preserve the current import entrypoint and avoid unnecessary churn.

Planned shape:

- re-export `Agent`, `AgentResponse`, and `PendingApproval` from the new runtime package
- remain intentionally small

Why:

- keeps current import sites stable
- avoids forcing unrelated changes in CLI/tests/docs beyond what is necessary

Target outcome:

- `agent/core.py` should become a thin compatibility surface rather than the main implementation home

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

### `agent/runtime/agent.py`

Responsibilities:

- contain the public `Agent` class
- own wiring of config, shell runner, policy, llm, tool registry, history, and pending approvals
- route built-in commands
- invoke helpers from `messages.py` and tool packages

Why:

- keeps the top-level runtime object focused on orchestration
- removes pure data/model and pure formatting concerns from the same file

Target outcome:

- keep the public `Agent` lifecycle readable in one place
- only introduce further splitting if readability still suffers after the first extraction pass

### Optional `agent/runtime/loop.py`

Responsibilities if introduced:

- host helpers for the iterative LLM/tool loop
- keep step-limit and loop mechanics together
- centralize logic that executes non-approval tool calls and collects `ToolResult`

Decision rule:

- create this file only if `agent/runtime/agent.py` would otherwise remain too large or too mentally dense after moving out data models and message helpers

Why this is optional:

- the project is still small
- unnecessary decomposition would reduce clarity rather than improve it

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

Practical extensibility standard:

After the refactor, adding a new tool should ideally require only:

1. a new tool implementation module or a focused addition to the right tool-family module
2. one registration update in `registry.py`
3. one matching test addition in the appropriate test module

It should not require editing unrelated existing tool implementations or central runtime behavior.

### `agent/tools/__init__.py`

Responsibilities:

- expose the public tool API
- provide compatibility re-exports so existing imports continue to work

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
- make failures easier to localize during future refactors

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

## Must-change modules vs mostly-stable modules

### Must-change modules

- `agent/tools.py`
- `agent/core.py`
- `tests/test_agent.py`

These are the direct structural hotspots.

### Mostly-stable modules

These should only receive minimal import-path or compatibility updates unless the implementation reveals a concrete need.

- `agent/cli.py`
- `agent/config.py`
- `agent/policy.py`
- `agent/shell.py`
- `agent/llm/__init__.py`
- `agent/llm/base.py`
- `agent/llm/types.py`
- `agent/llm/anthropic_client.py`
- `agent/llm/openai_client.py`
- `main.py`

This boundary is intentional and should protect the refactor from expanding into a repository-wide rewrite.

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

### 5. Treat file-count growth as acceptable only when it improves cohesion

Decision:

- new files are justified only when each file has a crisp responsibility and reduces a real hotspot

Why:

- prevents “split everything” refactors
- keeps the codebase ergonomic for a small team and a small repo

## Refactor guardrails

### Non-goals

- redesigning the tool approval product behavior
- redesigning shell policy semantics
- redesigning provider configuration or `.env` loading
- changing LLM request/response normalization logic
- introducing dynamic plugin discovery
- introducing a dependency injection framework
- renaming user-facing commands
- redesigning the CLI interaction model

### Allowed structural-only changes

- moving classes/functions into better-scoped modules
- adding re-export layers for compatibility
- renaming internal helper locations while preserving behavior
- reorganizing tests so they mirror subsystem boundaries
- making small import updates required by the new layout

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

## Migration strategy

Implementation should proceed in small safe steps:

1. create new packages/modules first
2. move shared tool contracts/types
3. move tool implementations and preserve exports
4. extract runtime data models and message helpers
5. re-check whether `agent/runtime/agent.py` still needs an additional `loop.py`
6. reduce `agent/core.py` to a thin compatibility layer
7. split tests and keep coverage green throughout
8. update README structure section only if it currently references old file layout in a way that becomes inaccurate

This order minimizes breakage and keeps each step verifiable.

## Validation strategy

The refactor is successful if all of the following are true:

1. tests still pass
2. public behavior is unchanged
3. public imports remain clean and unsurprising
4. `agent/tools.py` no longer contains the concrete tool implementations as a monolith
5. `agent/core.py` is reduced to a thin facade or otherwise falls comfortably within the size target
6. tests are split by subsystem rather than concentrated in a single file
7. no new dependency or framework complexity is introduced
8. adding a new tool would now be mostly additive under the practical standard defined above

## TODO

- [x] Create `agent/tools/` package and shared modules (`base.py`, `types.py`, `registry.py`)
- [x] Move `ReadFileTool` and `WriteFileTool` into `agent/tools/file_tools.py`
- [x] Move `GitTool` into `agent/tools/git_tool.py`
- [x] Add `agent/tools/__init__.py` re-exports and preserve current import ergonomics
- [x] Introduce `agent/runtime/` package for runtime models/helpers
- [x] Move `AgentResponse` and `PendingApproval` into `agent/runtime/types.py`
- [x] Extract runtime message builders/system prompt into `agent/runtime/messages.py`
- [x] Re-evaluate whether `agent/runtime/agent.py` still needs a separate `loop.py`
- [x] Reduce `agent/core.py` to a thin facade or slimmer orchestration module
- [x] Update imports across production code to the new module layout
- [x] Split `tests/test_agent.py` into subsystem-oriented test modules
- [ ] Run the full test suite and verify no behavior changes
- [ ] Update README only where structure descriptions become outdated
- [ ] Review final file sizes to ensure the refactor meets the 200–300 line target in practice
