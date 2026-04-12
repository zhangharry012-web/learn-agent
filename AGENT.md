# Project AGENT Guide

## Purpose

This file captures the stable working rules for modifying this repository with an AI coding agent. It is not a product specification. It is an execution guide intended to reduce rework, avoid fragile editing patterns, and keep remote collaborators able to observe progress in real time.

The rules below are derived from the recent project-structure refactor and the issues encountered during implementation and cleanup.

## Core workflow

1. Research before non-trivial changes.
2. Write or update a plan before implementing significant refactors or features.
3. Implement in small stable increments.
4. Validate locally before considering a round complete.
5. Commit and push after each completed modification round so the remote branch stays current.

## Commit and push discipline

This repository should follow a strict remote-visibility rule.

This is mandatory: once a modification round is complete, the result must be visible on the remote branch so the user can review it there immediately.

- After each completed round of file modification, create a commit and push it.
- Do not leave meaningful completed work only in the local working tree.
- If a round is incomplete because tests are broken or syntax is invalid, do not push that broken state unless the user explicitly asks for it.
- A “completed round” means the modified files for that round are in a stable enough state to review remotely.

Recommended sequence for each round:

1. modify files
2. run targeted validation
3. run broader validation if the targeted validation passes
4. update related planning/checklist documents if applicable
5. commit
6. push

## Safe editing strategy for high-risk text changes

When changes involve any of the following, use the safest possible editing approach:

- string escaping
- newline-heavy content
- heredoc blocks
- generated Python or shell source
- one script writing another script or source file
- nested quoting across Python, shell, JSON, or Markdown

### Preferred strategy

Directly rewrite the target file with the file-writing tool.

### Avoid

- script-generates-script patterns
- complex heredoc chains with follow-up commands on the same line
- multilayer escaping when a direct file rewrite is possible
- patching fragile string literals indirectly through generation scripts

### Reason

During the refactor, the main implementation instability came from escaping failures rather than architecture mistakes. Examples included:

- `\n` being expanded into real newlines while generating source code
- heredoc terminators being mixed with `&&` command chains
- Python interpreting shell remainder text as source because the heredoc was malformed
- generated files containing unterminated string literals

When a change is in this risk category, optimize for robustness over cleverness.

## Validation strategy

Always validate in two stages.

### Stage 1: local targeted validation

Before running the full test suite, validate the exact file or area that was touched.

Examples:

- print the relevant lines around a recently edited function
- import the modified module directly
- run a narrow test file first
- inspect the exact serialized source content if escaping was involved

### Stage 2: full validation

If the targeted validation passes, run the broader repository validation relevant to the change.

Do not skip Stage 1 and jump straight to the full suite when the change is local, syntax-sensitive, or escaping-sensitive. The narrow check is the guardrail that catches fragile failures early.

Typical order:

1. syntax/import smoke check
2. targeted tests
3. full unit test run

This prevents repeated full-suite runs when the real issue is a local syntax or import problem.

## Error-handling rules during implementation

When execution fails, do not blindly retry.

1. read the exact error message
2. identify whether the problem is business logic, import paths, shell parsing, or string escaping
3. if the issue is caused by escaping or heredoc composition, stop using that construction immediately
4. switch to direct file rewriting for the affected file
5. rerun the smallest meaningful validation first

### High-signal failures to watch for

- `SyntaxError: unterminated string literal`
- `EOL while scanning string literal`
- heredoc warnings such as `wanted 'PY'`
- Python parsing shell suffix text like `PY && ...`
- import failures caused by refactor compatibility gaps

## Refactor-specific guidance

When restructuring modules in this repository:

- prefer small cohesive packages over large multi-responsibility files
- preserve stable import surfaces where practical
- use compatibility re-exports if a refactor moves public classes or functions
- keep behavior unchanged unless the plan explicitly includes behavior changes
- split tests to mirror subsystem boundaries

### For this codebase specifically

The following patterns are preferred:

- `agent/core.py` can act as a thin compatibility facade
- `agent/runtime/` should hold runtime-specific models and orchestration helpers
- `agent/tools/` should hold tool contracts, registry logic, and concrete tool families
- tests should be grouped by subsystem instead of accumulating in one large file

## File size guideline

Aim for most files to stay within roughly 200–300 lines when practical.

This is a guideline, not a hard law. Do not split a file purely to satisfy a number if the split makes the design worse. Prefer responsibility-based decomposition over arbitrary file slicing.

## Documentation synchronization

If a change implements or materially advances an approved plan:

- update the plan checklist in the same round
- keep research/plan artifacts aligned with actual implementation status
- if a new repository-level working rule is learned, add it to `AGENT.md`

## Review and cleanup before closing a task

Before considering a task complete, check for:

- stale compatibility shims that are no longer needed
- old tests that should be removed or replaced
- import paths that can be simplified
- files that still exceed the intended size target without good reason
- outdated TODO states in planning documents

## Minimal completion checklist

A round is ready to commit and push when all of the following are true:

- edited files are syntactically valid
- local targeted validation passed
- broader validation passed for the affected area
- related plan/checklist state is updated if needed
- the round is coherent enough for remote review

## Default execution posture

When in doubt, prefer:

- simpler edits
- direct file rewrites over layered generation
- narrow validation before broad validation
- compatibility-preserving refactors
- smaller stable rounds with immediate push

These rules exist because they already proved necessary in this repository.
