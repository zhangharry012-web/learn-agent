import json
import tempfile
import unittest
from pathlib import Path

from agent.config import AgentConfig
from agent.verify import (
    VerifyPolicyError,
    classify_language,
    ensure_no_shell_tokens,
    extract_path_args,
    load_policy,
    relative_path,
    resolve_cwd,
    select_rule,
    validate_language_command,
)


class VerifyPolicyTests(unittest.TestCase):
    def test_classify_language_supports_go_python_ts(self):
        self.assertEqual(classify_language(['go', 'test', './...']), 'go')
        self.assertEqual(classify_language(['python', '-m', 'unittest']), 'python')
        self.assertEqual(classify_language(['npm', 'run', 'lint']), 'ts')

    def test_shell_tokens_are_rejected(self):
        with self.assertRaisesRegex(Exception, 'Shell composition tokens'):
            ensure_no_shell_tokens(['python', '-m', 'unittest', 'tests.test_tools;rm'])

    def test_validate_language_command_accepts_supported_patterns(self):
        validate_language_command(['python', '-m', 'unittest', 'tests.test_tools'])
        validate_language_command(['go', 'test', './...'])
        validate_language_command(['npm', 'run', 'lint'])

    def test_resolve_cwd_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(Exception, 'cwd escapes'):
                resolve_cwd(root, '../outside')

    def test_extract_path_args_normalizes_workspace_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = extract_path_args(['python', '-m', 'unittest', 'tests/test_tools.py'], root)
            self.assertEqual(paths, ['tests/test_tools.py'])

    def test_load_policy_reads_repo_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_dir = root / '.agent'
            policy_dir.mkdir()
            (policy_dir / 'verify-policy.json').write_text(
                json.dumps(
                    {
                        'version': 1,
                        'default_timeout_sec': 45,
                        'allow': [
                            {
                                'id': 'repo-go-test',
                                'argv_prefix': ['go', 'test'],
                                'cwd': '.',
                                'allowed_arg_regex': ['^\\./\\.\\.\\.$'],
                            }
                        ],
                        'deny_keywords': ['publish'],
                    }
                ),
                encoding='utf-8',
            )
            policy = load_policy(root, AgentConfig())
            self.assertIsNotNone(policy)
            self.assertEqual(policy.default_timeout_sec, 45)
            rule = policy.find_match(['go', 'test', './...'], '.', [])
            self.assertIsNotNone(rule)
            self.assertEqual(rule.rule_id, 'repo-go-test')

    def test_load_policy_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_dir = root / '.agent'
            policy_dir.mkdir()
            (policy_dir / 'verify-policy.json').write_text('{bad', encoding='utf-8')
            with self.assertRaises(VerifyPolicyError):
                load_policy(root, AgentConfig())

    def test_select_rule_uses_default_policy_without_repo_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = resolve_cwd(root, '.')
            relative_cwd = relative_path(root, cwd)
            rule = select_rule(['python', '-m', 'unittest', 'tests.test_tools'], relative_cwd, [], root, AgentConfig())
            self.assertEqual(rule.rule_id, 'python-unittest')

    def test_classify_language_supports_npx(self):
        self.assertEqual(classify_language(['npx', 'ts-node', 'test.ts']), 'ts')
        self.assertEqual(classify_language(['npx', 'tsx', 'test.ts']), 'ts')

    def test_validate_language_command_accepts_npx_ts_node(self):
        validate_language_command(['npx', 'ts-node', 'test.ts'])
        validate_language_command(['npx', 'tsx', 'test.ts'])

    def test_validate_language_command_rejects_npx_arbitrary(self):
        from agent.verify import VerifyCommandRejected
        with self.assertRaises(VerifyCommandRejected):
            validate_language_command(['npx', 'cowsay', 'hello'])

    def test_default_policy_matches_npx_ts_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = resolve_cwd(root, '.')
            relative_cwd = relative_path(root, cwd)
            rule = select_rule(['npx', 'ts-node', 'test.ts'], relative_cwd, [], root, AgentConfig())
            self.assertEqual(rule.rule_id, 'npx-ts-node')

    def test_default_policy_matches_npx_tsx(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = resolve_cwd(root, '.')
            relative_cwd = relative_path(root, cwd)
            rule = select_rule(['npx', 'tsx', 'app.ts'], relative_cwd, [], root, AgentConfig())
            self.assertEqual(rule.rule_id, 'npx-tsx')
