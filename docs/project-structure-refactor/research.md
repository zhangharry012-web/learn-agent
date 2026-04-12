# Project Structure Refactor Research

## Scope

This research covers the current `learn-agent` code layout after the multi-provider LLM work was merged into `main`. The goal of this research is to understand the current module boundaries in detail and identify the structural pain points that should be addressed before the next refactor. The target of the next change is not new end-user functionality; it is internal restructuring for better cohesion, improved extensibility, better alignment with the open-closed principle, and lower per-file complexity.

The current refactor request specifically calls out these goals:

- optimize folder structure
- keep related functionality together
- make future feature additions easier
- move closer to the open-closed principle
- keep files roughly within 200–300 lines where practical
- split `tools.py` into a package as an example

This document is based on a deep read of the current runtime, tooling, configuration, LLM integration, CLI entrypoint, and tests.

## Current top-level structure

The project currently has a small flat `agent/` package with several single-file modules and one already-split subpackage for LLM providers.

```text
learn-agent/
├── agent/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── core.py
│   ├── policy.py
│   ├── shell.py
│   ├── tools.py
│   └── llm/
│       ├── __init__.py
│       ├── anthropic_client.py
│       ├── base.py
│       ├── openai_client.py
│       └── types.py
├── tests/
│   └── test_agent.py
├── main.py
├── README.md
└── docs/
```

## Current file size baseline

The current line counts show exactly where structural pressure already exists.

| File | Lines | Observation |
|---|---:|---|
| `tests/test_agent.py` | 278 | Mixed concerns in one file; already at the upper boundary |
| `agent/core.py` | 225 | Runtime orchestration is concentrated in a single module |
| `agent/tools.py` | 212 | Multiple tool types and the registry live together |
| `agent/llm/openai_client.py` | 143 | Reasonable size |
| `agent/llm/anthropic_client.py` | 134 | Reasonable size |
| `agent/shell.py` | 71 | Small and cohesive |
| `agent/config.py` | 69 | Small, but may need a clearer role boundary later |
| `agent/policy.py` | 66 | Small and cohesive |
| `agent/cli.py` | 50 | Small and cohesive |
| `agent/llm/__init__.py` | 46 | Small factory/export module |

Nothing is catastrophically large yet, but the architecture is showing the classic pattern where a few “convenient” modules have started to accumulate unrelated responsibilities.

## Detailed findings by module

### `agent/core.py`

`agent/core.py` is the main orchestration layer. It currently contains:

- response data models:
  - `AgentResponse`
  - `PendingApproval`
- the `Agent` class
- default LLM construction logic
- built-in command handling (`help`, `exit`, `quit`)
- shell fallback logic when no LLM is configured
- the multi-step LLM tool execution loop
- approval-gated execution handling
- assistant message construction
- tool result message construction
- system prompt definition

This module is cohesive at a high level in the sense that it is all “agent runtime” behavior, but it is too concentrated. Several different concerns are intertwined:

1. session/runtime state
2. user command routing
3. LLM conversation loop
4. approval checkpoint state transitions
5. prompt construction
6. tool message serialization

The practical issue is not just line count. The larger problem is extension friction:

- adding a new approval mechanism would touch the same file
- adding richer built-in commands would touch the same file
- changing message-shaping rules would touch the same file
- changing runtime loop behavior would touch the same file

That means `core.py` is open for repeated modification whenever almost any runtime behavior changes. This is exactly the sort of hotspot that gradually violates open-closed expectations.

### `agent/tools.py`

`agent/tools.py` is the clearest candidate for package extraction. It currently contains:

- tool result model: `ToolExecutionResult`
- common base class: `BaseTool`
- concrete tools:
  - `ReadFileTool`
  - `WriteFileTool`
  - `GitTool`
- tool registry/builder: `build_tools(...)`
- path validation helper logic inside the base class
- approval prompt customization inside concrete tools

This file has two distinct structural problems.

#### Problem 1: multiple tool implementations in one module

Every additional tool will force edits to this file. Today there are only three tools, but future growth is obvious:

- shell execution tool
- search or grep tool
- directory listing tool
- patch/edit tool
- test running tool
- diff inspection tool
- project metadata tool

If all tools continue to live in one file, future additions will increase file length and will also require editing the same switch/registry area repeatedly.

#### Problem 2: registration is tightly coupled to concrete classes

`build_tools(...)` explicitly imports and instantiates every tool implementation within the same file. This is manageable with three tools, but it scales poorly because each new tool requires modifying the existing builder. That is acceptable in a small codebase, but it means the “extension point” is actually not very open.

This module should become a package with clearer layering:

- shared tool contracts/types
- file tools grouped together
- git tools grouped separately
- registry/factory separated from implementations

That would make adding a new tool mostly additive rather than requiring edits across unrelated tool code.

### `agent/llm/`

The `agent/llm/` package is already in a better state than the runtime and tools areas. It contains:

- `types.py` for unified provider-agnostic response models
- `base.py` for shared client abstraction
- `anthropic_client.py` for Anthropic-specific behavior
- `openai_client.py` for OpenAI-compatible behavior
- `__init__.py` for factory/export logic

This package is the strongest proof point in the current codebase that package-based decomposition is already working.

Important positive characteristics:

- provider-specific logic is isolated per file
- shared response models are separated from provider implementations
- factory logic is centralized but small
- adding a new provider has a natural landing zone

There is still some future refinement possible, such as moving provider registration into a dedicated registry module if the number of providers grows further, but this area is already much closer to the desired design style than `core.py` or `tools.py`.

### `agent/config.py`

`agent/config.py` is still small and understandable. It currently handles:

- defaults
- provider alias mapping constants
- `.env` file parsing
- value lookup helpers
- `AgentConfig` dataclass

The file is not too large. The main question here is architectural role clarity.

Today the module mixes:

- static configuration constants
- parsing/loading behavior
- runtime config dataclass construction

This is acceptable at current scale. It is not the highest-priority refactor target. However, if config surface area grows, it may later benefit from splitting into:

- constants/defaults
- env parsing/loading
- config dataclasses / normalization

That said, changing `config.py` now is optional and should only be done if it materially improves clarity without producing churn.

### `agent/cli.py`, `agent/policy.py`, `agent/shell.py`

These modules are each small and internally coherent.

- `cli.py` is a thin interactive entrypoint
- `policy.py` contains command safety evaluation logic
- `shell.py` wraps shell execution behavior

These modules do not currently need splitting. They are useful examples of good module boundaries in the existing codebase.

### `tests/test_agent.py`

The test suite is currently concentrated into one file containing:

- command policy tests
- tool tests
- config tests
- provider factory tests
- provider parsing tests
- stop reason normalization tests
- agent runtime approval-flow tests

This single file mirrors the same structural issue as `agent/core.py` and `agent/tools.py`: mixed domains in one place.

The problem is not only readability. Test organization also affects maintenance:

- when refactoring one subsystem, unrelated test sections create more merge friction
- future additions encourage appending to the same file
- locating failures is slower because the file is organized by accumulation rather than by subsystem boundary

A better layout would likely mirror the package structure, for example:

- `tests/test_config.py`
- `tests/test_policy.py`
- `tests/test_tools.py`
- `tests/test_agent.py` or `tests/test_runtime.py`
- `tests/test_llm_factory.py`
- `tests/test_llm_openai.py`
- `tests/test_llm_anthropic.py`

This would improve navigability and reinforce architectural boundaries.

## Cross-module coupling observations

### Coupling between `core.py` and `tools.py`

`Agent` currently depends directly on:

- `ToolExecutionResult`
- `build_tools(...)`
- the implicit assumptions of concrete tool approval behavior

This is workable, but the runtime is aware of tool approval semantics through direct object inspection (`tool.requires_approval`, `tool.approval_prompt(...)`, `tool.execute(...)`). That means the tool contract is important and should be stabilized as an explicit interface if tools are split into multiple files.

The good news is that the existing interface is already almost there. The base protocol is effectively:

- `definition()`
- `execute(payload)`
- `approval_prompt(payload)`
- `requires_approval`

That is a good boundary to preserve during refactor.

### Coupling between `core.py` and `llm/`

This coupling is healthier. `core.py` consumes unified abstractions from the LLM package:

- `BaseLLMClient`
- `ToolResult`
- `create_llm(...)`
- `extract_text(...)`

This is a stronger separation because `core.py` no longer needs to know provider-specific payload formats.

The structural lesson is important: the LLM package shows the architecture style that the tools/runtime area should move toward.

## Open-closed principle assessment

The request explicitly mentions open-closed alignment, so it is worth evaluating the current code against that goal.

### Areas that are already relatively open for extension

- `agent/llm/` provider implementations
- `agent/policy.py`
- `agent/shell.py`

### Areas that still require modification for common future changes

- `agent/tools.py`
  - every new tool changes the same file
  - registry logic and implementation logic change together
- `agent/core.py`
  - approval flow changes touch the central runtime file
  - message-shaping changes touch the central runtime file
  - built-in command changes touch the central runtime file
- `tests/test_agent.py`
  - every new subsystem test tends to append into the same file

So the biggest OCP gap is not abstract theory; it is a very practical maintenance issue: additive features currently still require editing the same few “center of gravity” files.

## Refactor opportunities

### Opportunity 1: turn `agent/tools.py` into a package

This is the clearest and highest-value change.

Candidate target shape:

```text
agent/tools/
├── __init__.py
├── base.py
├── types.py
├── registry.py
├── file_tools.py
└── git_tool.py
```

Potential benefits:

- each tool family has a clear home
- shared contracts are separated from implementations
- registration logic becomes a dedicated concern
- adding a tool becomes mostly additive
- file size stays controlled more naturally

### Opportunity 2: split runtime orchestration from runtime models/helpers

`agent/core.py` could be decomposed in multiple ways. The exact split matters less than keeping boundaries crisp.

Possible dimensions:

- `agent/runtime/types.py` for `AgentResponse` and `PendingApproval`
- `agent/runtime/loop.py` for the LLM tool loop
- `agent/runtime/messages.py` for assistant/tool-result message building
- `agent/runtime/agent.py` for high-level public `Agent`

The key is not to over-fragment. The current project is still small, so the split should be simple and purposeful rather than “framework-like”.

### Opportunity 3: split tests by subsystem

This is a low-risk, high-clarity change that should likely accompany the production refactor so test structure mirrors module structure.

### Opportunity 4: preserve stable public imports during restructure

Because the project is small, it is easy to accidentally break imports while moving files around. Refactor quality will be much better if the public import surface is preserved where reasonable.

For example:

- keep `from agent.core import Agent` working if possible, even if implementation moves underneath
- keep `from agent.tools import ReadFileTool` style imports working if backward compatibility is desired, via re-exports

This is not mandatory for internal-only code, but it reduces churn and makes the refactor safer.

## Constraints inferred from current code

1. The project values simple standard-library-first design.
   - There is no sign that a plugin framework or dependency injection container is wanted.
   - The refactor should stay lightweight.

2. Tool approval behavior is part of the user-facing runtime contract.
   - Refactor must not change which tools require approval unless explicitly planned.

3. LLM message structures have already been normalized once.
   - Runtime refactor should preserve the current provider-agnostic interaction pattern.

4. `.env` configuration behavior is now documented and tested.
   - Structural refactor should avoid incidental behavior changes here.

5. The codebase is small enough that too much package fragmentation would be counterproductive.
   - The goal is better cohesion, not maximum abstraction.

## Recommended scope for the next refactor

Based on the deep read, the highest-value scope is:

1. split `agent/tools.py` into a package
2. split `agent/core.py` into a small runtime package or equivalent smaller modules
3. split `tests/test_agent.py` by subsystem to mirror the new structure
4. keep `agent/llm/`, `agent/policy.py`, `agent/shell.py`, and `agent/cli.py` largely stable unless import paths need minimal updates

This scope directly addresses the user request while keeping the refactor focused.

## Risks to manage in planning

### Risk: over-engineering

A common failure mode would be introducing too many abstraction layers for a small project. For example, adding a complex plugin discovery system for tools would not be justified yet.

### Risk: moving code without improving boundaries

Simply splitting files by size would not be enough. The refactor needs to improve responsibility boundaries, not just reduce line counts.

### Risk: breaking tests or import ergonomics unnecessarily

If file moves are done without compatibility re-exports or mirrored test structure, the refactor may create churn out of proportion to its benefits.

### Risk: mixing structural refactor with behavior changes

This change should remain primarily structural. Behavioral changes should be avoided unless they are required to support the new structure.

## Summary

The codebase is in a healthy early stage, but it now has clear structural hotspots.

- `agent/llm/` already demonstrates a good package-oriented decomposition style.
- `agent/tools.py` is the clearest candidate for package extraction.
- `agent/core.py` has become the central runtime hotspot and should be decomposed by concern.
- `tests/test_agent.py` should be split to mirror subsystem boundaries.
- `cli.py`, `policy.py`, and `shell.py` are already appropriately sized and cohesive.

The next plan should therefore focus on a targeted refactor that improves cohesion and extension points without introducing unnecessary framework complexity.
