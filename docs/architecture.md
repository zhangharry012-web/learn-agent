# Architecture

## Overview

`learn-agent` is a minimal shell-interactive AI agent framework written in Python. Its purpose is to provide a clear execution path from user input to command handling and result output, while leaving enough structure for future expansion into a more capable agent runtime.

The current design is intentionally simple:

1. The CLI starts an interactive session.
2. The session reads a user command from standard input.
3. The agent core decides how to handle that command.
4. Shell-capable commands are executed through a dedicated shell runner.
5. The result is formatted and returned to the terminal.

## Design Goals

- Keep the first runnable version small and understandable
- Separate command input, decision logic, and shell execution
- Make extension points explicit for AI-assisted development
- Support local-first development and controlled execution

## Module Responsibilities

### `main.py`

- Repository-level startup entrypoint
- Delegates execution to the CLI module

### `agent/cli.py`

- Starts the interactive loop
- Reads user input
- Prints help text and formatted output
- Handles session lifecycle concerns such as `exit` and `quit`

### `agent/core.py`

- Contains the main `Agent` object
- Accepts raw user commands
- Handles built-in commands
- Delegates shell execution to the shell runner
- Normalizes responses into a stable result object

### `agent/shell.py`

- Wraps subprocess execution
- Captures stdout, stderr, and return codes
- Applies timeout and basic execution controls

## Execution Flow

```text
User Input
   |
   v
agent.cli: interactive loop
   |
   v
agent.core: command dispatch
   |
   +--> built-in command handling
   |
   +--> agent.shell: subprocess execution
             |
             v
        command result
             |
             v
        formatted terminal output
```

## Built-In Command Strategy

The minimal version supports a few built-in commands before falling back to shell execution:

- `help`: display available commands
- `exit`: terminate the session
- `quit`: terminate the session

This split keeps UX concerns inside the agent while still allowing the shell to remain the default execution backend.

## Result Contract

Commands are normalized into a structured result with the following fields:

- `ok`: whether the command succeeded
- `command`: the original user command
- `stdout`: captured standard output
- `stderr`: captured standard error
- `returncode`: process exit code
- `message`: optional high-level message for built-in commands

This contract keeps output easy to consume for both human users and future automated callers.

## Safety Baseline

The current scaffold is intentionally minimal and does not yet enforce a strict policy layer. For future versions, the recommended safety controls are:

- command allowlist or denylist rules
- confirmation hooks for destructive operations
- workspace-bound file operation policies
- timeout and process resource limits
- execution logging

## Extension Points

The current structure is prepared for future modules such as:

- `agent/memory.py`: session state and persistence
- `agent/router.py`: intent parsing and task routing
- `agent/tools/`: pluggable tool implementations
- `agent/models/`: LLM provider integration
- `agent/policy.py`: execution safety policy

## Suggested Next Steps

1. Add unit tests for shell execution and built-in command handling.
2. Introduce a configurable command policy layer.
3. Add a tool registry so shell execution is only one backend among several.
4. Add model integration for natural-language task decomposition.
5. Persist session history for debugging and replay.
