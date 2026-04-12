# Learn Agent

A Python-based AI agent project that uses the shell as its command interaction layer.

`learn-agent` is intended as a lightweight starting point for building local agents that accept commands, execute shell tasks, manage basic session context, and return structured results. The repository is designed to be readable by both human developers and AI agents.

When `.env` contains valid LLM credentials, the agent routes user requests through the configured provider and exposes three local tools:

- `read_file`: read local files directly without approval
- `write_file`: write local files after explicit human approval
- `git_run`: execute git commands after explicit human approval

## Features

- Python implementation with a simple CLI entrypoint
- Anthropic and OpenAI-compatible provider support
- `.env`-based local configuration
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
│   │   └── types.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── file_tools.py
│   │   ├── git_tool.py
│   │   ├── registry.py
│   │   └── types.py
│   └── llm/
│       ├── __init__.py
│       ├── anthropic_client.py
│       ├── base.py
│       ├── openai_client.py
│       └── types.py
├── tests/
│   ├── helpers.py
│   ├── test_agent_runtime.py
│   ├── test_config.py
│   ├── test_llm_anthropic.py
│   ├── test_llm_factory.py
│   ├── test_llm_openai.py
│   ├── test_policy.py
│   └── test_tools.py
└── docs/
    ├── architecture.md
    ├── multi-llm-provider/
    └── project-structure-refactor/
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

- Architecture: [docs/architecture.md](docs/architecture.md)
- Multi-provider design notes: [docs/multi-llm-provider/plan.md](docs/multi-llm-provider/plan.md)
- Multi-provider research notes: [docs/multi-llm-provider/research.md](docs/multi-llm-provider/research.md)

## Roadmap

- Add command routing and intent parsing
- Add memory and conversation persistence
- Add pluggable tool registry
- Add confirmation hooks on top of the current safety denylist
- Expand automated test coverage

## License

Released under the MIT License. See [LICENSE](LICENSE).
