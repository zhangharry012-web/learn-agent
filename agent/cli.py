from __future__ import annotations

from agent.core import Agent


PROMPT = "agent> "


def render_response(response: object) -> None:
    if getattr(response, "message", ""):
        print(response.message)

    if getattr(response, "stdout", ""):
        print(response.stdout)

    if getattr(response, "stderr", ""):
        print(response.stderr)

    if not getattr(response, "ok", True):
        print(f"[exit code: {response.returncode}]")


def main() -> int:
    agent = Agent()

    print("Learn Agent interactive shell")
    print("Type 'help' for built-in commands. Type 'exit' to quit.")

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


if __name__ == "__main__":
    raise SystemExit(main())
