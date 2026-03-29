# Learn Agent

A Python-based AI agent project that uses the shell as its command interaction layer.

`learn-agent` is intended as a lightweight starting point for building local agents that accept commands, execute shell tasks, manage basic session context, and return structured results. The repository is designed to be readable by both human developers and AI agents.

## Features

- Python implementation with a simple CLI entrypoint
- Shell-backed command execution
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

### 3. Run the agent

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
agent> pwd
agent> echo hello
agent> ls
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
