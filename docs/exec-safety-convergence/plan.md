# Exec Safety Convergence Plan

## Overview

This iteration further narrows the practical surface area around `exec` without opening arbitrary shell execution. The main strategy is to move common read-only shell-style inspection needs into approval-free, purpose-built tools and to sharpen each tool description so the LLM can distinguish them reliably.

## Tool responsibility boundaries

| Tool | Primary responsibility | Explicit non-goals |
|---|---|---|
| `read_file` | Read UTF-8 file contents, including direct `cat`-style access and line-ranged reads | Directory layout, git state, arbitrary shell |
| `inspect_path` | Workspace layout inspection with `pwd` / `ls` / `find` / `du` semantics | File contents, git state, arbitrary shell |
| `git_inspect` | Read-only git state/history with `status` / `diff` / `log` / `show` | Non-git filesystem inspection, git mutation |
| `read_only_command` | Narrow shell-style file summaries/metadata with `head` / `tail` / `wc` / `stat` / `file` | Full file contents via `cat`, directory traversal, git state, arbitrary shell composition |
| `exec` | Approval-gated fallback for broader non-git shell commands only when no narrower tool fits | Common read-only inspection that should use the narrower tools |

## Why this change

The previous state still left an ambiguity gap around shell-flavored read-only requests. In practice, prompts like `cat README.md`, `head -n 20 ...`, `wc -l ...`, or `file ...` could attract the overly broad `exec` tool even when a safer alternative was available.

This change resolves that in two ways:

1. by adding a narrower approval-free command subset for common read-only summary/metadata operations
2. by explicitly teaching each tool description what it should and should not be used for

## Safety decisions

### `cat` is intentionally not added to the new tool

`cat` maps too directly to full file-content access, which is already better modeled by `read_file` because `read_file`:

- has structured path + line-range inputs
- avoids shell semantics entirely
- better communicates intent to the model
- keeps direct text reading separate from shell-like summary commands

So the new tool explicitly rejects `cat` and tells the caller to use `read_file`.

### The new command subset stays narrow

Allowed commands are:

- `head`
- `tail`
- `wc`
- `stat`
- `file`

Each command is validated structurally before execution. Path arguments remain workspace-bounded, pipelines/composition tokens are disallowed, and unsupported flags are rejected.

### `exec` remains broad but clearly demoted

`exec` is still the only general shell escape hatch, but it remains approval-gated and now explicitly says it is not the right tool for:

- `cat` or direct file reading
- `pwd` / `ls` / `find` / `du`
- `git status` / `git diff` / `git log` / `git show`

## Validation rules for `read_only_command`

- `head` / `tail`
  - only `-n` is allowed
  - exactly one target file is allowed
  - line counts must be positive and bounded
- `wc`
  - only `-l`, `-w`, or `-c` are allowed
  - exactly one target file is allowed
- `stat` / `file`
  - exactly one target path is allowed
  - no extra flags are allowed
- `cat`
  - always rejected with guidance to use `read_file`
- all commands
  - no shell composition
  - no path escape outside workspace root

## Tests updated

This round verifies:

- default tool registry now includes `read_only_command`
- `read_only_command` uses argv-based execution
- `cat` is rejected with a boundary-guidance error
- path escape attempts are rejected
- runtime execution of `read_only_command` does not require approval
- `exec` still requires approval
- full suite still passes
