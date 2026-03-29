# Learn Agent

A Python-based AI agent project that uses the shell as its command interaction layer.

`learn-agent` is intended as a lightweight starting point for building local agents that accept commands, execute shell tasks, manage basic session context, and return structured results. The repository is designed to be readable by both human developers and AI agents.

When `ANTHROPIC_API_KEY` is configured, the agent routes user requests through Anthropic Claude and exposes three local tools:

- `read_file`: read local files directly without approval
- `write_file`: write local files after explicit human approval
- `git_run`: execute git commands after explicit human approval

## Features

- Python implementation with a simple CLI entrypoint
- Anthropic Claude integration through the official Python SDK
- Tool-based local file and git access
- Session-oriented interaction loop
- Clear separation between CLI, agent logic, and shell runner
- Basic safety policy for dangerous shell commands
- Minimal structure that is easy to extend

## Use Cases

- Build a local command-line AI assistant
- Prototype shell-capable automation agents
- Learn agent execution flow and tool orchestration
- Provide an AI-agent-friendly project skeleton for further development

## Project Structure

```text
learn-agent/
├── README.md
├── LICENSE
├── main.py
├── requirements.txt
├── agent/
│   ├── __init__.py
│   ├── cli.py
│   ├── core.py
│   └── shell.py
└── docs/
    └── architecture.md
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

### 3. Configure Anthropic

```bash
export ANTHROPIC_API_KEY=your_api_key
```

Optional:

```bash
export ANTHROPIC_MODEL=claude-sonnet-4-20250514
```

### 4. Run the agent

```bash
python main.py
```

Or:

```bash
python -m agent.cli
```

## Example Commands

Inside the interactive shell:

```text
agent> help
agent> read the README and summarize it
agent> create a file named notes.txt with three bullet points
agent> yes
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

## Documentation

- Architecture: [docs/architecture.md](/Users/zhanghr/Documents/github/zhangharry/learn-agent/docs/architecture.md)

## Roadmap

- Add command routing and intent parsing
- Add model provider integration
- Add memory and conversation persistence
- Add pluggable tool registry
- Add confirmation hooks on top of the current safety denylist
- Expand automated test coverage

## License

Released under the MIT License. See [LICENSE](/Users/zhanghr/Documents/github/zhangharry/learn-agent/LICENSE).
