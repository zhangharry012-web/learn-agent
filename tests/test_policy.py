import unittest

from agent.policy import CommandPolicy


class CommandPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = CommandPolicy()

    def test_allows_safe_command(self):
        decision = self.policy.evaluate('echo hello')
        self.assertTrue(decision.allowed)

    def test_blocks_rm_command(self):
        decision = self.policy.evaluate('rm -rf tmp')
        self.assertFalse(decision.allowed)
