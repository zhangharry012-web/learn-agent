# Research: Read-Only Directory Inspection Tool

## Task

Implement a new project-level tool that supports common shell-style folder inspection without changing harness permissions. The tool must remain read-only, avoid arbitrary shell execution, integrate with the current approval model so it does not require confirmation, and preserve the existing approval requirement for higher-risk tools.

## Current tool architecture

The project already has a compact tool layer under `agent/tools/`:

- `base.py`: shared `BaseTool` with `definition()`, `execute()`, `approval_prompt()`, and `resolve_path()` helpers.
- `registry.py`: `build_tools(...)` instantiates enabled tools and returns a `name -> tool` map.
- `file_tools.py`: `read_file` is unapproved; `write_file` and `edit_file` require approval.
- `exec_tool.py`: unrestricted shell command execution via `ShellRunner.run(...)`, always requires approval.
- `git_tool.py`: scoped git command execution via `ShellRunner.run_argv(...)`, always requires approval.

The runtime does not hardcode tool names except through the tool registry and the approval flow. That means adding a new tool is a localized change as long as:

1. it subclasses `BaseTool`
2. it is registered in `build_tools(...)`
3. its `requires_approval` flag is `False`

## Approval flow behavior

Approval is managed in `agent/runtime/agent.py`, not inside individual tools.

Important behavior:

- If an LLM response contains tool calls, the runtime loops over them.
- For each tool call, `tool.requires_approval` determines whether the runtime pauses and asks the user.
- Unapproved tools execute immediately inside `_run_llm_loop(...)`.
- Approved tools create `PendingApproval` and resume only after a later `yes/no` user turn.

This is exactly the extension point needed for the new inspection tool. No approval framework change is necessary if the tool is marked as non-approval.

## Existing runtime/tool contracts

### Tool result contract

All tools return `ToolExecutionResult(ok: bool, content: str)`.

Current conventions:

- successful structured results are usually JSON-encoded strings
- errors are returned as plain strings or parsing errors
- the runtime passes the raw tool result back into the LLM as a `tool_result`

### Tool schema contract

Each tool exposes:

- `name`
- `description`
- `input_schema`

The LLM sees these definitions and can choose tools accordingly.

## Shell execution and safety constraints

`agent/shell.py` exposes two execution styles:

- `run(command: str, cwd=...)`: uses `shell=True`; suitable for arbitrary shell execution, higher risk
- `run_argv(argv: List[str], cwd=...)`: executes argv directly without shell parsing; safer for a constrained read-only inspection tool

For this task, `run_argv(...)` is the correct primitive. It avoids shell metacharacter expansion and arbitrary composed command execution.

## Existing path safety behavior

`BaseTool.resolve_path(raw_path)` resolves a relative path under `workspace_root` and rejects escapes outside the workspace. This is already the correct primitive for any path-based read-only inspection tool.

That means the new tool should reuse `resolve_path(...)` rather than inventing new path validation.

## Existing tests relevant to this task

### `tests/test_tools.py`

Covers:

- file tools behavior
- `ExecTool` shell-runner integration
- `GitTool` argv integration
- default tool registry contents

This is the primary place for unit tests of the new tool.

### `tests/test_agent_runtime.py`

Covers:

- approval-required write/edit/exec/git flows
- shell fallback behavior
- observability event logging and cleanup

This is the correct place to verify that the new tool executes without approval when invoked by the LLM.

### `tests/helpers.py`

`FakeShellRunner` already captures both `command_calls` and `argv_calls`, which is useful for verifying the new tool uses argv execution instead of shell-string execution.

## README and design-doc state

The README already documents:

- available tools at a high level
- observability logs and lifecycle
- interactive workflow

The observability rotation plan in `docs/observability-rotation/plan.md` is not the right design doc for a new tool feature. A separate focused design doc under `docs/` is more appropriate, so the new feature does not get mixed into the rotation plan.

## Gaps / implementation opportunities

### 1. No safe directory-inspection tool exists

Current options are:

- `read_file`: too narrow; cannot inspect directory structure
- `exec`: can do inspection but is arbitrary shell, so it requires approval

This leaves a usability gap for common read-only shell-style exploration.

### 2. Tool registry default set is centralized

The enabled default tuple in `AgentConfig.enabled_tools` and the registry default fallback in `build_tools(...)` both enumerate the tool names directly. Adding a new default tool requires updating both places unless that duplication is cleaned up during implementation.

### 3. Approval semantics are already expressive enough

No policy or approval refactor is required. The new tool can simply be another non-approval tool.

## Likely good implementation shape

The safest and cleanest approach is a dedicated tool such as `inspect_path` or `list_dir` that supports a small enum of actions rather than raw commands.

A strong option is a single read-only inspection tool with actions like:

- `pwd`
- `ls`
- `find`
- `du`

This keeps the mental model close to shell usage while constraining behavior enough to remain approval-free.

## Safety requirements implied by the task

To satisfy the user request, the implementation must explicitly avoid:

- arbitrary shell text input
- shell pipelines or command composition
- write/delete/move operations
- network operations
- path escape outside workspace

That implies the input schema should be structured, not raw shell.

## Edge cases to account for

1. Nonexistent path
   - should fail cleanly with a readable error
2. File path passed to a directory-oriented action
   - either support sensible behavior (`du` on file, `ls` on file) or reject explicitly
3. Deep recursive find
   - should be bounded with a max depth or result trimming to avoid excessive output
4. Huge directories
   - `find` / `ls` / `du` output may become large; output bounding or explicit limits are advisable
5. Hidden files
   - likely should be controllable via an option rather than always included
6. Sort order / deterministic output
   - deterministic ordering will keep tests stable and outputs easier to inspect

## Reuse opportunities discovered during research

These existing utilities should be reused instead of reimplemented:

- `BaseTool.resolve_path(...)` for workspace-bounded path handling
- `ShellRunner.run_argv(...)` for safe argv-based subprocess execution
- `FakeShellRunner.argv_calls` in tests to verify non-shell execution

## Architecture constraints that should remain unchanged

- `exec` must stay approval-gated
- `git_run` must stay approval-gated
- file mutation tools must stay approval-gated
- approval logic should remain centralized in runtime, not duplicated in tools
- tool outputs should continue flowing back through the same `ToolExecutionResult` mechanism

## Recommendation for planning

The plan should:

1. add a dedicated read-only inspection tool module under `agent/tools/`
2. define a structured action enum rather than accepting raw shell text
3. use `run_argv(...)` for command execution
4. keep the tool approval-free by design
5. update registry/config defaults and tests
6. document the feature in README
7. add a dedicated design doc under `docs/` for the new tool rather than overloading the observability docs
