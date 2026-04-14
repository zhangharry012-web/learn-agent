from __future__ import annotations

from agent.core import Agent


PROMPT = 'agent> '


def render_response(response: object) -> None:
    if getattr(response, 'message', ''):
        print(response.message)
    if getattr(response, 'stdout', ''):
        print(response.stdout)
    if getattr(response, 'stderr', ''):
        print(response.stderr)
    if not getattr(response, 'ok', True):
        print(f'[exit code: {response.returncode}]')


def main() -> int:
    agent = Agent()
    print('Learn Agent interactive shell')
    print("Type 'help' for built-in commands. Type 'exit' to quit.")
    if agent.llm is None:
        print('No LLM credentials configured. Falling back to direct shell execution.')
    else:
        base_url_enabled = 'yes' if agent.config.llm_base_url else 'no'
        print(
            'LLM enabled '
            f'(provider={agent.config.llm_provider}, model={agent.config.llm_model}, base_url={base_url_enabled}) '
            'with read_file, write_file, edit_file, exec, and git_inspect tools.'
        )
    while True:
        try:
            command = input(PROMPT)
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print()
            continue
        response = agent.handle(command)
        render_response(response)
        if response.should_exit:
            break
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
