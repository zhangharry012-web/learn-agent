import unittest

from agent.core import Agent
from agent.policy import CommandPolicy
from agent.shell import ShellRunner


class CommandPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = CommandPolicy()

    def test_allows_safe_command(self) -> None:
        decision = self.policy.evaluate("echo hello")
        self.assertTrue(decision.allowed)

    def test_blocks_rm_command(self) -> None:
        decision = self.policy.evaluate("rm -rf tmp")
        self.assertFalse(decision.allowed)
        self.assertIn("not allowed", decision.reason)

    def test_blocks_invalid_shell_syntax(self) -> None:
        decision = self.policy.evaluate("echo 'unterminated")
        self.assertFalse(decision.allowed)
        self.assertIn("unable to parse", decision.reason)


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = Agent(shell_runner=ShellRunner(timeout=5))

    def test_help_command(self) -> None:
        response = self.agent.handle("help")
        self.assertTrue(response.ok)
        self.assertIn("Built-in commands", response.message)

    def test_exit_command(self) -> None:
        response = self.agent.handle("exit")
        self.assertTrue(response.ok)
        self.assertTrue(response.should_exit)

    def test_executes_safe_shell_command(self) -> None:
        response = self.agent.handle("echo hello")
        self.assertTrue(response.ok)
        self.assertEqual(response.stdout, "hello")

    def test_blocks_dangerous_shell_command(self) -> None:
        response = self.agent.handle("rm -rf tmp")
        self.assertFalse(response.ok)
        self.assertEqual(response.returncode, 126)
        self.assertIn("blocked by safety policy", response.stderr)


if __name__ == "__main__":
    unittest.main()
