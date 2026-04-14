from agent.llm import BaseLLMClient
from agent.shell import ShellRunner


class FakeLLM(BaseLLMClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate(self, *, system_prompt, messages, tools):
        self.calls.append(
            {
                'system_prompt': system_prompt,
                'messages': messages,
                'tools': tools,
            }
        )
        return self.responses.pop(0)


class FakeShellRunner(ShellRunner):
    def __init__(self, shell_result):
        super().__init__(timeout=1)
        self.shell_result = shell_result
        self.command_calls = []
        self.argv_calls = []

    def run(self, command, cwd=None, timeout=None):
        self.command_calls.append({'command': command, 'cwd': cwd, 'timeout': timeout})
        return self.shell_result

    def run_argv(self, argv, cwd=None, timeout=None):
        self.argv_calls.append({'argv': list(argv), 'cwd': cwd, 'timeout': timeout})
        return self.shell_result
