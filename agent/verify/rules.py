from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern
import re

from agent.config import AgentConfig
from agent.shell import ShellResult


SHELL_META_PATTERN = re.compile(r'(\|\||&&|[;<>`]|\$\()')
SUPPORTED_LANGUAGES = frozenset({'go', 'python', 'ts'})
ALLOWED_NODE_SCRIPT_NAMES = frozenset({'test', 'lint', 'build', 'typecheck', 'check'})
ALLOWED_TS_EXECUTABLES = frozenset({'npm', 'pnpm', 'yarn'})
ALLOWED_PYTHON_EXECUTABLES = frozenset({'python', 'python3', 'pytest', 'ruff', 'mypy'})


class VerifyPolicyError(ValueError):
    pass


class VerifyCommandRejected(ValueError):
    pass


class VerifyPolicyMismatch(ValueError):
    pass


class VerifyRule:
    def __init__(
        self,
        *,
        rule_id: str,
        argv_exact: Optional[List[str]] = None,
        argv_prefix: Optional[List[str]] = None,
        cwd: str = '.',
        max_timeout_sec: Optional[int] = None,
        allowed_arg_regex: Optional[List[str]] = None,
        allowed_path_patterns: Optional[List[str]] = None,
        allow_generated_artifacts: bool = False,
        description: str = '',
    ) -> None:
        self.rule_id = rule_id
        self.argv_exact = list(argv_exact) if argv_exact is not None else None
        self.argv_prefix = list(argv_prefix) if argv_prefix is not None else None
        self.cwd = cwd
        self.max_timeout_sec = max_timeout_sec
        self.allowed_arg_patterns: List[Pattern[str]] = [re.compile(p) for p in allowed_arg_regex or []]
        self.allowed_path_patterns: List[Pattern[str]] = [re.compile(p) for p in allowed_path_patterns or []]
        self.allow_generated_artifacts = allow_generated_artifacts
        self.description = description

    def matches(self, argv: List[str], relative_cwd: str, path_args: List[str]) -> bool:
        if self.argv_exact is not None and argv != self.argv_exact:
            return False
        if self.argv_prefix is not None and argv[: len(self.argv_prefix)] != self.argv_prefix:
            return False
        if relative_cwd != self.cwd:
            return False
        if self.allowed_arg_patterns:
            for arg in argv[len(self.argv_prefix or self.argv_exact or []):]:
                if self._is_option(arg):
                    continue
                if not any(pattern.match(arg) for pattern in self.allowed_arg_patterns):
                    return False
        if self.allowed_path_patterns:
            for path_arg in path_args:
                if not any(pattern.match(path_arg) for pattern in self.allowed_path_patterns):
                    return False
        return True

    def _is_option(self, arg: str) -> bool:
        return arg.startswith('-')


class VerifyPolicySet:
    def __init__(
        self,
        *,
        default_timeout_sec: int,
        allow_rules: List[VerifyRule],
        deny_keywords: List[str],
    ) -> None:
        self.default_timeout_sec = default_timeout_sec
        self.allow_rules = allow_rules
        self.deny_keywords = [keyword.lower() for keyword in deny_keywords]

    def find_match(self, argv: List[str], relative_cwd: str, path_args: List[str]) -> Optional[VerifyRule]:
        joined = ' '.join(argv).lower()
        if any(keyword in joined for keyword in self.deny_keywords):
            return None
        for rule in self.allow_rules:
            if rule.matches(argv, relative_cwd, path_args):
                return rule
        return None


def default_policy() -> VerifyPolicySet:
    return VerifyPolicySet(
        default_timeout_sec=120,
        deny_keywords=['install', 'publish', 'deploy', 'curl', 'wget', 'bash', 'sh', 'npx'],
        allow_rules=[
            VerifyRule(
                rule_id='python-unittest',
                argv_prefix=['python', '-m', 'unittest'],
                allowed_arg_regex=[r'^discover$', r'^-s$', r'^-p$', r'^[A-Za-z0-9_./-]+$'],
            ),
            VerifyRule(
                rule_id='python3-unittest',
                argv_prefix=['python3', '-m', 'unittest'],
                allowed_arg_regex=[r'^discover$', r'^-s$', r'^-p$', r'^[A-Za-z0-9_./-]+$'],
            ),
            VerifyRule(
                rule_id='python-pytest',
                argv_prefix=['python', '-m', 'pytest'],
                allowed_arg_regex=[r'^-q$', r'^-x$', r'^-k$', r'^-m$', r'^[A-Za-z0-9_./:-]+$'],
            ),
            VerifyRule(
                rule_id='pytest',
                argv_prefix=['pytest'],
                allowed_arg_regex=[r'^-q$', r'^-x$', r'^-k$', r'^-m$', r'^[A-Za-z0-9_./:-]+$'],
            ),
            VerifyRule(
                rule_id='ruff-check',
                argv_prefix=['ruff', 'check'],
                allowed_arg_regex=[r'^--fix$', r'^[A-Za-z0-9_./-]+$'],
                max_timeout_sec=60,
            ),
            VerifyRule(
                rule_id='mypy',
                argv_prefix=['mypy'],
                allowed_arg_regex=[r'^--strict$', r'^[A-Za-z0-9_./-]+$'],
                max_timeout_sec=60,
            ),
            VerifyRule(
                rule_id='go-test',
                argv_prefix=['go', 'test'],
                allowed_arg_regex=[r'^-run$', r'^-count=1$', r'^-v$', r'^\./\.\.\.$', r'^\./[A-Za-z0-9_./-]+$', r'^[A-Za-z0-9_./-]+$'],
            ),
            VerifyRule(rule_id='npm-test', argv_exact=['npm', 'run', 'test']),
            VerifyRule(rule_id='npm-lint', argv_exact=['npm', 'run', 'lint'], max_timeout_sec=60),
            VerifyRule(rule_id='npm-build', argv_exact=['npm', 'run', 'build'], max_timeout_sec=180),
            VerifyRule(rule_id='npm-typecheck', argv_exact=['npm', 'run', 'typecheck'], max_timeout_sec=120),
            VerifyRule(rule_id='pnpm-test', argv_exact=['pnpm', 'test']),
            VerifyRule(rule_id='pnpm-lint', argv_exact=['pnpm', 'lint'], max_timeout_sec=60),
            VerifyRule(rule_id='pnpm-build', argv_exact=['pnpm', 'build'], max_timeout_sec=180),
            VerifyRule(rule_id='pnpm-typecheck', argv_exact=['pnpm', 'typecheck'], max_timeout_sec=120),
            VerifyRule(rule_id='yarn-test', argv_exact=['yarn', 'test']),
            VerifyRule(rule_id='yarn-lint', argv_exact=['yarn', 'lint'], max_timeout_sec=60),
            VerifyRule(rule_id='yarn-build', argv_exact=['yarn', 'build'], max_timeout_sec=180),
            VerifyRule(rule_id='yarn-typecheck', argv_exact=['yarn', 'typecheck'], max_timeout_sec=120),
        ],
    )


def load_policy(workspace_root: Path, config: AgentConfig) -> Optional[VerifyPolicySet]:
    policy_path = (workspace_root / config.verify_policy_file).resolve()
    try:
        policy_path.relative_to(workspace_root)
    except ValueError as exc:
        raise VerifyPolicyError('Verify policy path escapes the workspace root.') from exc
    if not policy_path.exists():
        return None
    try:
        payload = json.loads(policy_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise VerifyPolicyError('Verify policy file is not valid JSON.') from exc
    allow_rules = []
    for item in payload.get('allow', []):
        rule_id = str(item.get('id') or '').strip()
        if not rule_id:
            raise VerifyPolicyError('Verify policy rules must define id.')
        allow_rules.append(
            VerifyRule(
                rule_id=rule_id,
                argv_exact=_list_of_strings(item.get('argv_exact')),
                argv_prefix=_list_of_strings(item.get('argv_prefix')),
                cwd=str(item.get('cwd') or '.'),
                max_timeout_sec=_optional_int(item.get('max_timeout_sec')),
                allowed_arg_regex=_list_of_strings(item.get('allowed_arg_regex')) or [],
                allowed_path_patterns=_list_of_strings(item.get('allowed_path_patterns')) or [],
                allow_generated_artifacts=bool(item.get('allow_generated_artifacts', False)),
                description=str(item.get('description') or ''),
            )
        )
    return VerifyPolicySet(
        default_timeout_sec=int(payload.get('default_timeout_sec') or config.verify_default_timeout_sec),
        allow_rules=allow_rules,
        deny_keywords=[str(keyword) for keyword in payload.get('deny_keywords', [])],
    )


def classify_language(argv: List[str]) -> str:
    executable = argv[0]
    if executable == 'go':
        return 'go'
    if executable in ALLOWED_PYTHON_EXECUTABLES:
        return 'python'
    if executable in ALLOWED_TS_EXECUTABLES:
        return 'ts'
    raise VerifyCommandRejected('Only go, python, and ts verification commands are supported.')


def ensure_no_shell_tokens(argv: List[str]) -> None:
    for token in argv:
        if SHELL_META_PATTERN.search(token):
            raise VerifyCommandRejected('Shell composition tokens are not allowed in verify_command.')


def validate_language_command(argv: List[str]) -> None:
    language = classify_language(argv)
    if language == 'go':
        if len(argv) < 2 or argv[1] != 'test':
            raise VerifyCommandRejected('Only go test is allowed for Go verification commands.')
        return
    if language == 'python':
        executable = argv[0]
        if executable in {'python', 'python3'}:
            if len(argv) < 3 or argv[1] != '-m' or argv[2] not in {'unittest', 'pytest'}:
                raise VerifyCommandRejected('Only python -m unittest and python -m pytest are allowed.')
            return
        if executable == 'pytest':
            return
        if executable == 'ruff':
            if len(argv) < 2 or argv[1] != 'check':
                raise VerifyCommandRejected('Only ruff check is allowed for Ruff verification commands.')
            return
        if executable == 'mypy':
            return
    if language == 'ts':
        executable = argv[0]
        if executable == 'npm':
            if argv[1:] not in [['run', 'test'], ['run', 'lint'], ['run', 'build'], ['run', 'typecheck']]:
                raise VerifyCommandRejected('Only npm run test/lint/build/typecheck are allowed.')
            return
        if executable in {'pnpm', 'yarn'}:
            if argv[1:] not in [['test'], ['lint'], ['build'], ['typecheck']]:
                raise VerifyCommandRejected('Only pnpm/yarn test/lint/build/typecheck are allowed.')
            return


def extract_path_args(argv: List[str], workspace_root: Path) -> List[str]:
    path_args: List[str] = []
    skip_next = False
    for index, arg in enumerate(argv[1:], start=1):
        if skip_next:
            skip_next = False
            continue
        if arg in {'-k', '-m', '-run', '-s', '-p'}:
            skip_next = True
            continue
        if arg.startswith('-'):
            continue
        if _looks_like_path_arg(arg):
            resolved = (workspace_root / arg).resolve()
            try:
                relative = resolved.relative_to(workspace_root)
            except ValueError as exc:
                raise VerifyCommandRejected('Path escapes the workspace root.') from exc
            path_args.append(str(relative) if str(relative) else '.')
    return path_args


def resolve_cwd(workspace_root: Path, raw_cwd: str) -> Path:
    candidate = (workspace_root / (raw_cwd or '.')).resolve()
    try:
        candidate.relative_to(workspace_root)
    except ValueError as exc:
        raise VerifyCommandRejected('Verify command cwd escapes the workspace root.') from exc
    return candidate


def relative_path(workspace_root: Path, path: Path) -> str:
    relative = path.relative_to(workspace_root)
    return str(relative) if str(relative) else '.'


def select_rule(
    argv: List[str],
    relative_cwd: str,
    path_args: List[str],
    workspace_root: Path,
    config: AgentConfig,
) -> VerifyRule:
    repo_policy = load_policy(workspace_root, config)
    if repo_policy is not None:
        match = repo_policy.find_match(argv, relative_cwd, path_args)
        if match is None:
            raise VerifyPolicyMismatch('Verify command is not allowed by the repository policy.')
        return match
    if config.verify_require_repo_policy:
        raise VerifyPolicyMismatch('Repository verify policy is required before auto verification can run.')
    match = default_policy().find_match(argv, relative_cwd, path_args)
    if match is None:
        raise VerifyCommandRejected('Verify command is outside the safe verification subset.')
    return match


def timeout_for_rule(rule: VerifyRule, config: AgentConfig) -> int:
    if rule.max_timeout_sec is not None and rule.max_timeout_sec > 0:
        return rule.max_timeout_sec
    return config.verify_default_timeout_sec


def json_result(result: ShellResult, argv: List[str], cwd: str, rule: VerifyRule) -> str:
    payload = {
        'argv': argv,
        'cwd': cwd,
        'rule_id': rule.rule_id,
        'returncode': result.returncode,
        'stdout': result.stdout,
        'stderr': result.stderr,
    }
    return json.dumps(payload, ensure_ascii=False)


def _looks_like_path_arg(arg: str) -> bool:
    if arg in {'.', './...'}:
        return True
    if '/' in arg or arg.startswith('.'):
        return True
    if arg.endswith(('.py', '.go', '.ts', '.tsx', '.js', '.jsx')):
        return True
    return False


def _list_of_strings(value: Any) -> Optional[List[str]]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise VerifyPolicyError('Verify policy arrays must contain only strings.')
    return list(value)


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    return int(value)
