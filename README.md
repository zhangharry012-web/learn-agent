# Learn Agent

A Python-based AI agent project that uses the shell as its command interaction layer.

`learn-agent` is intended as a lightweight starting point for building local agents that accept commands, execute shell tasks, manage basic session context, and return structured results. The repository is designed to be readable by both human developers and AI agents.

When `.env` contains valid LLM credentials, the agent routes user requests through the configured provider and exposes local tools:

- `read_file`: read UTF-8 text file contents directly without approval
- `write_file`: write local files directly inside the project root without approval
- `edit_file`: edit existing local files directly inside the project root without approval
- `inspect_path`: inspect workspace layout with bounded `pwd` / `ls` / `find` / `du` actions without approval
- `read_only_command`: run a narrow approval-free read-only command subset for `head` / `tail` / `wc` / `stat` / `file`
- `git_inspect`: inspect repository state with a narrow read-only git subset without approval
- `verify_command`: run safe verification commands such as go/python/ts test, lint, and build flows without approval when they match the verification policy
- `git_run`: execute broader git commands after explicit human approval
- `exec`: execute arbitrary shell commands after explicit human approval

## Features

- Python implementation with a simple CLI entrypoint
- Anthropic and OpenAI-compatible provider support
- `.env`-based local configuration
- Tool-based local file and shell access
- Session-oriented interaction loop
- Clear separation between CLI, agent logic, and shell runner
- Basic safety policy for dangerous shell commands
- Structured observability logs under a dedicated log directory
- Minimal structure that is easy to extend

## Use Cases

- Build a local command-line AI assistant
- Prototype shell-capable automation agents
- Learn agent execution flow and tool orchestration
- Inspect LLM and runtime behavior through local observability logs
- Provide an AI-agent-friendly project skeleton for further development

## Project Structure

```text
learn-agent/
├── README.md
├── AGENT.md
├── .env.example
├── LICENSE
├── main.py
├── requirements.txt
├── agent/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── core.py                  # thin compatibility facade
│   ├── policy.py
│   ├── shell.py
│   ├── runtime/
│   │   ├── __init__.py
│   │   ├── agent.py
│   │   ├── messages.py
│   │   ├── observability.py
│   │   └── types.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── exec_tool.py
│   │   ├── file_tools.py
│   │   ├── git_inspect_tool.py
│   │   ├── git_tool.py
│   │   ├── inspect_tool.py
│   │   ├── read_only_command_tool.py
│   │   ├── registry.py
│   │   ├── types.py
│   │   └── verify_command_tool.py
│   ├── verify/
│   │   ├── __init__.py
│   │   └── rules.py
│   └── llm/
│       ├── __init__.py
│       ├── anthropic_client.py
│       ├── base.py
│       ├── openai_client.py
│       └── types.py
├── docs/
│   ├── architecture.md
│   ├── exec-safety-convergence/
│   │   └── plan.md
│   ├── observability-expansion/
│   │   ├── plan.md
│   │   └── research.md
│   ├── multi-llm-provider/
│   └── project-structure-refactor/
├── tests/
│   ├── helpers.py
│   ├── test_agent_runtime.py
│   ├── test_config.py
│   ├── test_llm_anthropic.py
│   ├── test_llm_factory.py
│   ├── test_llm_openai.py
│   ├── test_policy.py
│   └── test_tools.py
└── logs/
    └── observability/
        ├── events.jsonl
        └── sessions/
```

## Quick Start

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create local config

```bash
cp .env.example .env
```

`.env` has the highest priority and is the only configuration source used by the app at runtime.
Do not commit `.env`.

Example Anthropic config:

```bash
LLM_PROVIDER=anthropic
LLM_API_KEY=your_api_key
LLM_MODEL=claude-sonnet-4-20250514
OBSERVABILITY_ENABLED=true
OBSERVABILITY_LOG_DIR=logs/observability
OBSERVABILITY_PREVIEW_CHARS=2000
```

Example DeepSeek config:

```bash
LLM_PROVIDER=deepseek
LLM_API_KEY=your_api_key
LLM_MODEL=deepseek-chat
LLM_BASE_URL=https://api.deepseek.com
```

Backward-compatible Anthropic aliases are still supported in `.env`:

```bash
ANTHROPIC_API_KEY=your_api_key
ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

### 4. Run the agent

```bash
python main.py
```

Or:

```bash
python -m agent.cli
```

## Observability Logs

The agent writes structured observability logs to a dedicated directory by default. Logs rotate hourly using UTC date-hour partitions, and historical log files older than 30 days are cleaned up automatically unless you override the retention window.

```text
logs/observability/events/YYYY-MM-DD/HH.jsonl
logs/observability/sessions/<session_id>/YYYY-MM-DD/HH.jsonl
```

The JSONL stream includes clearer stage-oriented events for:

- `command.received`, `command.completed`, and `command.blocked`
- `llm.response.completed`, `llm.loop_limit.exceeded`, and `llm.panic`
- `tool.approval.requested` and `tool.approval.completed`
- `tool.execution.completed`
- `shell.execution.completed`
- `verify.execution.requested`, `verify.execution.completed`, and `verify.execution.rejected`
- `session.summary`

Lifecycle reference:

```text
user input
  -> command.received
     -> built-in command
        -> command.completed
     -> shell fallback
        -> command.blocked / shell.execution.completed
        -> command.completed
     -> llm loop
        -> llm.response.completed
        -> tool.approval.requested
        -> tool.approval.completed
        -> verify.execution.requested / verify.execution.completed / verify.execution.rejected (only for verify_command)
        -> tool.execution.completed
        -> llm.loop_limit.exceeded (only when the loop cap is hit)
        -> command.completed
  -> exit / quit
     -> command.completed
     -> session.summary
```

`command.received` is the entry event for a single user turn. It is emitted immediately after the input is normalized and before the agent branches into built-in handling, shell fallback, approval handling, or the LLM loop. `command.completed` closes that same user turn, while the LLM/tool/shell events describe intermediate stages inside the turn.

Each event timestamp is stored in UTC with millisecond precision for easier manual inspection.

Turn boundaries vs. inner stages:

- `command.received` and `command.completed` describe the outer lifecycle of one user turn.
- `llm.response.completed`, `tool.*`, `shell.execution.completed`, and `command.blocked` describe intermediate stages inside that turn.
- One user turn can contain multiple `llm.response.completed` or `tool.execution.completed` events, but it still starts with `command.received` and ends with `command.completed`.
- `session.summary` is emitted once per session when the user closes the session with `exit` or `quit`, and the final summary is also attached to the returned `AgentResponse.session_summary`.

`session.summary` currently includes:

- `command_count`
- `llm_call_count`
- `tool_call_count`
- `tool_call_breakdown`
- `tool_success_count`
- `tool_failure_count`
- `tool_outcome_breakdown`
- `shell_command_count`
- `token_usage.input_tokens`
- `token_usage.output_tokens`
- `token_usage.total_tokens`

Useful configuration:

```text
OBSERVABILITY_ENABLED=true
OBSERVABILITY_LOG_DIR=logs/observability
OBSERVABILITY_PREVIEW_CHARS=2000
OBSERVABILITY_RETENTION_HOURS=720
```

Verification configuration:

```text
VERIFY_AUTO_APPROVE_ENABLED=true
VERIFY_POLICY_FILE=.agent/verify-policy.json
VERIFY_DEFAULT_TIMEOUT_SEC=120
VERIFY_REQUIRE_REPO_POLICY=false
```

A repository can define its own verification policy in `.agent/verify-policy.json`. This repository now includes a starter example file at that path. The initial safe verification subset supports common Go, Python, and TypeScript test/lint/build flows. When a command falls outside the safe subset or does not match the repository policy, the agent must use `exec` instead.

For `verify_command`, observability now emits:

- `verify.execution.requested`: a verify run was requested and passed initial payload parsing
- `verify.execution.completed`: a verify run matched policy and finished execution
- `verify.execution.rejected`: a verify run was rejected before execution because validation or policy matching failed


Useful inspection commands:

```bash
find logs/observability/events -type f | sort
find logs/observability/sessions -type f | sort
grep '"event_type": "llm.response.completed"' logs/observability/events/$(date -u +%F)/$(date -u +%H).jsonl
```

## Tool Boundary Guide

The safety model now intentionally separates common inspection intents so the model can avoid the broader `exec` fallback.

| Intent | Correct tool | Notes |
|---|---|---|
| Read the contents of a specific text file | `read_file` | This is the replacement for `cat`, and also for most `head`/`tail` style reading when exact file text is needed |
| List directories or inspect workspace layout | `inspect_path` | Use for `pwd`, `ls`, `find`, and `du` style structure inspection |
| Read file metadata or a lightweight summary | `read_only_command` | Use for bounded `head`, `tail`, `wc`, `stat`, and `file` |
| Inspect git repository state/history | `git_inspect` | Use for `git status`, `git diff`, `git log`, and `git show` |
| Run broader non-git shell commands | `exec` | Approval-gated fallback only when none of the narrower tools apply |

## Read-Only Git Inspection Tool

The agent exposes an approval-free `git_inspect` tool for a small read-only git subset. This avoids using the broader approval-gated `git_run` tool for common repository inspection requests.

Supported subcommands:

- `git status`
- `git diff`
- `git log`
- `git show`

Safety characteristics:

- only a fixed read-only subcommand set is allowed
- inline git config overrides are rejected
- broader git mutations still require approval through `git_run`
- non-git filesystem inspection should use `inspect_path`

Example tool payloads:

```json
{"args": "status --short"}
{"args": "diff -- README.md"}
{"args": "log --oneline -5"}
```

## Read-Only Inspection Tool

The agent exposes an approval-free `inspect_path` tool for common workspace inspection tasks that do not need arbitrary shell execution.

Supported actions:

- `pwd`
- `ls`
- `find`
- `du`

Safety characteristics:

- all file and inspection paths are restricted to the project root
- tools reject path traversal outside that root
- `pwd` returns the project-root marker directly instead of invoking a subprocess
- argv-based subprocess execution is used for bounded `ls` / `find` / `du` actions
- no delete, move, or network behavior
- file contents should use `read_file`
- git state should use `git_inspect`
- `exec` remains approval-gated for anything broader

Example tool payloads:

```json
{"action": "pwd"}
{"action": "ls", "path": "agent"}
{"action": "find", "path": "agent", "max_depth": 2}
{"action": "du", "path": "tests"}
```

## Read-Only Command Tool

The agent exposes an approval-free `read_only_command` tool for a very small non-git shell-style subset that is narrower than `exec`.

Supported commands:

- `head`
- `tail`
- `wc`
- `stat`
- `file`

Safety characteristics:

- `cat` is intentionally rejected so direct file contents route to `read_file`
- only one target path is allowed per request
- target paths are restricted to the project root
- `head` and `tail` only allow `-n` and enforce bounded output sizes
- `wc` only allows `-l`, `-w`, or `-c`
- `stat` and `file` allow no extra flags
- arbitrary shell composition still requires approval through `exec`

Example tool payloads:

```json
{"args": "head -n 20 README.md"}
{"args": "tail -n 10 tests/test_tools.py"}
{"args": "wc -l agent/tools/file_tools.py"}
{"args": "stat README.md"}
{"args": "file README.md"}
```

## Example Commands

Inside the interactive shell:

```text
agent> help
agent> read the README and summarize it
agent> create a file named notes.txt with three bullet points
agent> show me git status
agent> no
agent> exit
```

## AI-Agent-Friendly Conventions

This project is intentionally structured for machine readability and automation:

- Stable file layout
- Explicit module responsibilities
- Predictable command-line entrypoint
- Plain-text interaction contract
- Clear extension points for future tools, memory, or model integration
- Baseline safeguards for obviously destructive commands
- Structured runtime logging for debugging and inspection

## Documentation

- Architecture: [docs/architecture.md](docs/architecture.md)
- Exec safety convergence plan: [docs/exec-safety-convergence/plan.md](docs/exec-safety-convergence/plan.md)
- Observability expansion plan: [docs/observability-expansion/plan.md](docs/observability-expansion/plan.md)
- Observability expansion research: [docs/observability-expansion/research.md](docs/observability-expansion/research.md)
- Observability rotation plan: [docs/observability-rotation/plan.md](docs/observability-rotation/plan.md)
- Observability rotation research: [docs/observability-rotation/research.md](docs/observability-rotation/research.md)
- Read-only inspection research: [docs/read-only-inspection/research.md](docs/read-only-inspection/research.md)
- Multi-provider design notes: [docs/multi-llm-provider/plan.md](docs/multi-llm-provider/plan.md)
- Multi-provider research notes: [docs/multi-llm-provider/research.md](docs/multi-llm-provider/research.md)

## Roadmap

- Add command routing and intent parsing
- Add memory and conversation persistence
- Expand pluggable tool registry
- Add confirmation hooks on top of the current safety denylist
- Expand automated test coverage
- Add lightweight log summary and browsing utilities for observability output

## License

Released under the MIT License. See [LICENSE](LICENSE).
