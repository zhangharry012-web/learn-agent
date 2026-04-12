# Tool Expansion Plan

## Overview

This change will extend the current tool system with two additive capabilities:

- `edit_file` for approval-gated exact search-and-replace file edits
- `exec` for approval-gated direct shell command execution inside the workspace

The implementation will preserve the existing runtime and provider abstractions. It will add new concrete tools, slightly extend shell execution support, update the prompt/CLI so the new tools are discoverable to the LLM and user, and add focused tests for the new behavior.

## Target file structure

```text
learn-agent/
├── agent/
│   ├── cli.py                          # advertise the updated default tool set
│   ├── shell.py                        # add cwd support to run(...)
│   ├── runtime/
│   │   └── messages.py                 # teach the LLM when to use the new tools
│   └── tools/
│       ├── __init__.py                 # export EditFileTool and ExecTool
│       ├── file_tools.py               # add EditFileTool next to Read/Write
│       ├── exec_tool.py                # new ExecTool implementation
│       └── registry.py                 # register the expanded default tool set
├── tests/
│   ├── helpers.py                      # may remain unchanged if current fake shell is sufficient
│   ├── test_agent_runtime.py           # add approval-flow tests for edit_file / exec
│   └── test_tools.py                   # add unit tests for EditFileTool / ExecTool / registry
├── research.md                         # task-specific research artifact
└── plan.md                             # task-specific implementation plan
```

## Architecture diagram

```text
LLM
  |
  v
runtime.Agent
  |
  v
build_tools(...)
  |
  |-----------------------------|------------------------------|
  |                             |                              |
  v                             v                              v
Read/Write/Edit file tools   GitTool                        ExecTool
  |                             |                              |
  |                             v                              v
  |                      ShellRunner.run_argv(...)      ShellRunner.run(..., cwd=workspace)
  |
  v
workspace file mutation via BaseTool.resolve_path(...)
```

## Module design

### `agent/tools/file_tools.py`

Add `EditFileTool` to the existing file tool family.

Responsibilities:

- resolve the target file relative to the workspace
- read existing UTF-8 text from disk
- perform exact-text replacement
- reject ambiguous or unsafe no-op inputs
- rewrite the file with updated content
- return a structured JSON result summary

Proposed interface:

```python
class EditFileTool(BaseTool):
    name = 'edit_file'
    requires_approval = True
    input_schema = {
        'type': 'object',
        'properties': {
            'path': {'type': 'string'},
            'search': {'type': 'string'},
            'replace': {'type': 'string'},
            'replace_all': {'type': 'boolean'},
        },
        'required': ['path', 'search', 'replace'],
    }
```

Execution rules:

- if `search` is empty, fail with a clear error
- if file does not exist, fail
- if `search` is not found, fail
- if `replace_all` is true, replace every exact match and report the count
- otherwise replace only the first match and report a count of `1`

Approval prompt shape:

- summarize `path`
- summarize whether replacement is single or all matches
- summarize byte size of search/replace strings only if useful
- avoid dumping large raw content into the approval prompt

### `agent/tools/exec_tool.py`

Create a new generic shell execution tool.

Responsibilities:

- accept a shell command string
- execute it in the workspace root
- return command, return code, stdout, stderr in the existing JSON envelope style
- require approval for every execution

Proposed interface:

```python
class ExecTool(BaseTool):
    name = 'exec'
    requires_approval = True
    input_schema = {
        'type': 'object',
        'properties': {
            'command': {'type': 'string'},
        },
        'required': ['command'],
    }
```

Execution path:

- call `shell_runner.run(command, cwd=self.workspace_root)`
- serialize the resulting `ShellResult` into the same shape used by `GitTool`

Approval prompt shape:

- `Approve shell command? <command>`

### `agent/shell.py`

Extend `ShellRunner.run(...)` with optional `cwd` support.

Why:

- `exec` needs direct shell semantics
- the command should run inside the workspace root, not the ambient current directory
- this is cleaner than emulating shell execution with `run_argv(['/bin/sh', '-lc', ...])`

Proposed signature:

```python
def run(self, command: str, cwd: Path = None) -> ShellResult: ...
```

Behavior that stays unchanged:

- timeout handling
- `shell=True`
- trimmed stdout/stderr
- returncode and timeout contract

### `agent/tools/registry.py`

Expand the default enabled tool set and registration logic.

Target default set:

- `read_file`
- `write_file`
- `edit_file`
- `git_run`
- `exec`

Why:

- these should be available by default to the agent once implemented
- registration remains explicit and additive

### `agent/tools/__init__.py`

Export:

- `EditFileTool`
- `ExecTool`

This keeps the public package surface coherent and allows direct test imports.

### `agent/runtime/messages.py`

Update the system prompt to explain the intended routing:

- use `read_file` before claiming file contents
- use `edit_file` for focused in-place edits to existing files
- use `write_file` for creating files or broad rewrites
- use `git_run` for git operations
- use `exec` for direct shell commands such as inspection, validation, or non-git local execution
- continue to request approval-required tools one at a time from the model perspective

This is important because the runtime can support the new tools immediately, but model behavior depends heavily on prompt guidance.

### `agent/cli.py`

Update the startup banner so it reflects the actual default tool inventory.

## Design decisions and trade-offs

### 1. Exact search-and-replace instead of regex editing

Chosen approach:

- exact-text replacement only

Why:

- simpler schema
- easier approval reasoning
- deterministic tests
- lower risk than regex semantics in a small local agent

Trade-off:

- less expressive than regex or patch hunks
- acceptable for the first version because the request explicitly framed the feature as 搜索替换

### 2. Dedicated `ExecTool` instead of folding into `GitTool`

Chosen approach:

- new `agent/tools/exec_tool.py`

Why:

- separates generic shell execution from repository-specific git operations
- preserves a clearer policy distinction for the LLM
- scales better if more shell-adjacent tools are added later

Trade-off:

- one extra small file
- worth it for cohesion and extensibility

### 3. Extend `ShellRunner.run(...)` rather than shell-wrapping `run_argv(...)`

Chosen approach:

- add optional `cwd` to `run(...)`

Why:

- keeps shell execution API honest
- avoids unnecessary wrapper invocation details
- improves reuse for any future shell-string-based operation

Trade-off:

- small signature change in `ShellRunner`
- low risk because current call sites are minimal and backward-compatible

### 4. Keep `EditFileTool` in `file_tools.py`

Chosen approach:

- place it alongside `ReadFileTool` and `WriteFileTool`

Why:

- same domain: workspace file access/mutation
- file still remains within the repository's practical size target after one additive class

Trade-off:

- `file_tools.py` grows
- still acceptable at current scale

## What stays unchanged

The following should not require architectural changes for this task:

- provider-specific LLM parsing in `agent/llm/*`
- runtime approval state model in `agent/runtime/types.py`
- main orchestration shape in `agent/runtime/agent.py`
- config loading in `agent/config.py`
- AGENT.md, unless implementation reveals a genuinely new long-term repository rule

## Usage expectations

### `edit_file`

Expected tool call shape:

```json
{
  "path": "README.md",
  "search": "old text",
  "replace": "new text",
  "replace_all": false
}
```

### `exec`

Expected tool call shape:

```json
{
  "command": "python -m unittest -q"
}
```

## Validation strategy

Stage 1 local validation should cover the touched area first:

1. import smoke for the new tool exports
2. focused `tests/test_tools.py`
3. focused `tests/test_agent_runtime.py`

Stage 2 broader validation:

1. full `python -m unittest discover -s tests -p 'test*.py' -v`

## Extensibility after this change

After this implementation, adding a future tool should remain mostly additive:

1. add a new tool module or extend the appropriate tool-family module
2. register it in `agent/tools/registry.py`
3. expose it through `agent/tools/__init__.py` if part of the public surface
4. add focused tool/runtime tests
5. optionally adjust prompt wording if the tool changes model routing behavior

This keeps the current practical open-closed standard intact.

## TODO

- [ ] Add `EditFileTool` to `agent/tools/file_tools.py`
- [ ] Add `ExecTool` in `agent/tools/exec_tool.py`
- [ ] Extend `ShellRunner.run(...)` to accept optional `cwd`
- [ ] Export the new tools from `agent/tools/__init__.py`
- [ ] Register `edit_file` and `exec` in `agent/tools/registry.py`
- [ ] Update `agent/runtime/messages.py` system prompt for the new tools
- [ ] Update `agent/cli.py` banner text for the new tool inventory
- [ ] Add tool tests for `EditFileTool`, `ExecTool`, and registry defaults
- [ ] Add runtime approval-flow tests covering `edit_file` and `exec`
- [ ] Run targeted validation
- [ ] Run full test validation
- [ ] Commit and push the implementation round
