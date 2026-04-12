# Tool Expansion Research

## Scope

This research covers the current tool system in `learn-agent` and the concrete changes needed to add two new tools:

- `edit_file`: edit an existing workspace file through search-and-replace operations
- `exec`: execute a shell command directly

The goal is to extend the current architecture with minimal behavioral disruption while preserving the repository's existing approval model, runtime loop, provider-agnostic tool protocol, and packageized tool structure.

## Current architecture relevant to this change

### Runtime orchestration

The active runtime entrypoint is `agent/runtime/agent.py`, re-exported through `agent/core.py`. The `Agent` object owns:

- config loading
- shell runner creation
- tool registry construction via `build_tools(...)`
- message history
- approval state via `PendingApproval`
- the multi-turn LLM loop

The runtime exposes tools to the LLM by calling `tool.definition()` for each registered tool and passing the resulting schema to the provider client.

Tool execution flow is:

1. LLM emits one or more tool calls
2. runtime appends an assistant message containing tool call metadata
3. if any tool in that batch requires approval, runtime pauses and stores all requested tool calls in `PendingApproval`
4. when user approves, runtime executes each stored tool call in order
5. runtime turns each execution result into a `ToolResult`
6. runtime appends a tool-result message and continues the loop

A key runtime safety rule already exists in the system prompt in `agent/runtime/messages.py`:

- read before making claims about file contents
- only request `write_file` when the user wants file creation/modification
- only request `git_run` for repository operations
- never request more than one approval-required tool call in the same response

That last line is stricter than the runtime implementation. The runtime can actually hold and execute multiple pending approval-required tool calls because `PendingApproval.tool_calls` is a list and `_handle_approval(...)` iterates over all of them. So the prompt is using policy to keep model behavior narrow, not reflecting a hard runtime limitation.

### Tool package structure

The tool system is already split into a package:

- `agent/tools/base.py`
- `agent/tools/types.py`
- `agent/tools/file_tools.py`
- `agent/tools/git_tool.py`
- `agent/tools/registry.py`
- `agent/tools/__init__.py`

This is the correct landing zone for the requested feature.

#### `BaseTool`

`BaseTool` provides:

- common metadata fields: `name`, `description`, `input_schema`, `requires_approval`
- `definition()` to expose tool schema to providers
- `approval_prompt(...)` default formatting
- `resolve_path(...)` to constrain file operations to `workspace_root`

This means the new `edit_file` tool should inherit `BaseTool` and reuse `resolve_path(...)` rather than introducing its own path safety logic.

#### `ToolExecutionResult`

`ToolExecutionResult` is only:

```python
@dataclass
class ToolExecutionResult:
    ok: bool
    content: str
```

So each tool is responsible for serializing rich results into a string, typically JSON. Existing tools already return JSON strings for success and plain text for error in exceptional paths.

#### Existing file tools

`agent/tools/file_tools.py` currently contains:

- `ReadFileTool`
- `WriteFileTool`

`ReadFileTool`:

- reads UTF-8 text
- optionally slices by `start_line` and `end_line`
- returns JSON with path, selected range, and content
- does not require approval

`WriteFileTool`:

- writes or appends text to a resolved path
- creates parent directories if needed
- requires approval
- returns JSON with path, mode, and bytes written
- customizes approval prompt to summarize path/mode/byte count

This file is the natural place for `EditFileTool`, because it is another workspace file mutation primitive.

### Existing shell execution capability

The project already has shell execution infrastructure in `agent/shell.py`:

- `ShellRunner.run(command: str)` executes with `shell=True`
- `ShellRunner.run_argv(argv, cwd=...)` executes without shell interpolation
- both return `ShellResult` with command, return code, stdout, stderr, and `ok`

There is also an existing approval-gated command tool in `agent/tools/git_tool.py`:

- `GitTool` wraps `shell_runner.run_argv(['git'] + args, cwd=self.workspace_root)`
- it requires approval
- it returns a JSON object containing command, returncode, stdout, stderr

This is strong evidence that `exec` should be implemented as a sibling tool to `GitTool`, reusing `ShellRunner`, approval gating, and the same result envelope shape.

## LLM/provider integration impact

The provider clients do not hardcode tool names.

### `agent/llm/openai_client.py`

The OpenAI-compatible client converts the runtime-provided tool definitions into OpenAI function specs using each tool's `name`, `description`, and `input_schema`.

Response parsing is generic:

- tool name comes from provider output
- arguments are parsed as JSON
- runtime later resolves tool name against its registry

### `agent/llm/anthropic_client.py`

The Anthropic client also forwards tool schemas generically and parses tool calls into provider-agnostic `ToolCall` instances.

Conclusion: adding new tools does not require provider code changes unless the tool schema shape triggers a parser edge case. For this request, no provider-layer modification should be necessary.

## CLI and user-facing wording impact

`agent/cli.py` currently prints:

- when LLM is enabled: `with read_file, write_file, and git_run tools.`

That line becomes outdated once `edit_file` and `exec` exist. It should be updated so the runtime advertises the actual default tool set.

`agent/runtime/messages.py` also hardcodes tool guidance in the system prompt. If the default tool set changes, the prompt should be updated to teach the model when to use:

- `edit_file` instead of broad overwrite writes for narrow edits
- `exec` for direct shell commands
- `git_run` only for repository-scoped git operations

Without prompt updates, the model may keep overusing `write_file` or avoid `exec` even after the tools exist.

## Tests and current coverage gaps

### Existing tool tests

`tests/test_tools.py` currently covers:

- `ReadFileTool`
- `WriteFileTool`
- `GitTool`

It does not cover:

- registration defaults in `build_tools(...)`
- approval prompts for all tools
- direct shell execution tools
- search-and-replace semantics
- failure cases around missing text, path escapes, or repeated replacements

### Existing runtime tests

`tests/test_agent_runtime.py` validates:

- fallback shell behavior without LLM
- approval flow for `write_file`
- approval flow for `git_run`

It does not explicitly test:

- approval flow for a second non-git mutating tool
- approval flow for direct shell execution tool calls
- mixed tool inventory visibility to the fake LLM

The existing test patterns are sufficient to extend without new test infrastructure.

## Design constraints for the new tools

### `edit_file`

The request says "编辑文件（搜索替换）", so the primary behavior should be explicit search-and-replace rather than patch syntax, line-edit scripting, or regex-first mutation.

A safe minimal contract is:

- `path`: relative workspace path
- `search`: exact text to find
- `replace`: replacement text
- optional `replace_all`: whether to replace all matches or only the first

Expected behavior should be deterministic and conservative:

- resolve path within workspace using `resolve_path(...)`
- require that the file already exists
- read as UTF-8 text
- if `search` is empty, fail clearly instead of allowing an undefined operation
- if `search` is not found, return an error result rather than silently succeeding
- write the updated content back atomically enough for current project scale using normal file rewrite
- return JSON summarizing path and replacement count
- require approval, because it mutates files

A search-and-replace exact match contract is simpler and less fragile than introducing regexes or patch hunks in the first step.

### `exec`

The request says "直接执行 shell 命令", so the tool should accept a single shell command string and execute it through `ShellRunner.run(...)`.

Expected contract:

- `command`: shell command string

Expected behavior:

- require approval
- execute within `workspace_root`
- return JSON with command, returncode, stdout, stderr

The current `ShellRunner.run(...)` does not accept a `cwd` argument, only the argv variant does. That is a structural mismatch, because `exec` should run inside the repository workspace rather than the current process directory by accident.

So there are two implementation options:

1. extend `ShellRunner.run(...)` to accept optional `cwd`
2. fake shell execution through `run_argv(['/bin/sh', '-lc', command], cwd=...)`

Option 1 is cleaner because it preserves the interface meaning of `run(...)` while making it symmetric with `run_argv(...)`.

## Best-fit implementation approach

### Add `EditFileTool` to `agent/tools/file_tools.py`

Why:

- it belongs to the existing file mutation family
- it can reuse `BaseTool.resolve_path(...)`
- it keeps file mutation concerns grouped together

### Add `ExecTool` in a new `agent/tools/exec_tool.py`

Why:

- it is a shell execution family, closer to `GitTool` than to file tools
- it avoids turning `git_tool.py` into a mixed command execution module
- it keeps room for future shell-adjacent tools such as `grep`, `ls`, or test-running wrappers

### Update `agent/tools/registry.py`

`build_tools(...)` should include the new default names:

- `edit_file`
- `exec`

Current default set is `('read_file', 'write_file', 'git_run')`. It should become a fuller default tool inventory.

### Update `agent/tools/__init__.py`

Export the two new tool classes so imports remain simple and tests can import them directly.

### Update `agent/runtime/messages.py`

Adjust system prompt wording so the model knows:

- use `read_file` before claims about file contents
- use `edit_file` for focused in-place edits
- use `write_file` for creating files or broad rewrites
- use `exec` for direct shell commands
- use `git_run` for git actions only
- keep the single approval-required tool-call guidance unless we explicitly want the model to batch approvals later

### Update `agent/cli.py`

Refresh the enabled-tool text to match the new default inventory.

## Open questions resolved by current codebase context

### Should `edit_file` support regex?

No for the first version.

The repository currently values robustness and narrow semantics. Exact search-and-replace is easier to explain, test, and validate than regex replacement.

### Should `exec` bypass approval because the CLI already runs shell commands without an LLM?

No.

The no-LLM fallback mode is an explicitly different path: direct user command entry. In tool mode, the LLM is choosing the action, so approval should remain mandatory just as it is for `write_file` and `git_run`.

### Should `edit_file` live in its own file?

Not necessary yet.

`file_tools.py` is currently small enough that adding one more cohesive file-editing class remains within the repository's size guideline.

### Should `exec` and `git_run` be unified?

Not for now.

`git_run` communicates a narrower, more controllable intent to the model. Keeping a dedicated git tool and a dedicated generic shell tool gives the prompt cleaner policy distinctions and preserves a lower-risk path for repository operations.

## Risks to handle carefully

1. **Prompt drift**: if the system prompt is not updated, the LLM may continue using `write_file` for narrow edits and underuse `edit_file`.
2. **Working directory ambiguity**: if `exec` runs outside `workspace_root`, it may behave unpredictably or violate user expectations.
3. **Silent no-op edits**: if `edit_file` succeeds when `search` is missing, debugging will be painful. It should fail loudly.
4. **Approval-flow regressions**: new approval-required tools must integrate cleanly with `PendingApproval`.
5. **Line-count drift**: `file_tools.py` should stay reasonably compact after adding `EditFileTool`; if it becomes too dense, a later split into `read_tool.py` / `write_edit_tools.py` could be considered, but that is not required now.

## Recommended scope for the next plan

The next plan should cover:

- adding `EditFileTool` and `ExecTool`
- extending `ShellRunner.run(...)` with optional `cwd`
- registering/exporting the new tools
- updating system prompt and CLI wording
- adding focused tool and runtime tests
- leaving AGENT.md unchanged unless the implementation reveals a genuinely new long-term workflow rule
