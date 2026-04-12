from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class ShellResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class ShellRunner:
    """Runs shell commands with a small, explicit interface."""

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout

    def run(self, command: str, cwd: Path = None) -> ShellResult:
        try:
            completed = subprocess.run(
                command,
                shell=True,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                cwd=str(cwd) if cwd is not None else None,
            )
            return ShellResult(
                command=command,
                returncode=completed.returncode,
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
            )
        except subprocess.TimeoutExpired:
            return ShellResult(
                command=command,
                returncode=124,
                stdout='',
                stderr=f'Command timed out after {self.timeout} seconds.',
            )

    def run_argv(self, argv: List[str], cwd: Path = None) -> ShellResult:
        try:
            completed = subprocess.run(
                argv,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                cwd=str(cwd) if cwd is not None else None,
            )
            return ShellResult(
                command=' '.join(argv),
                returncode=completed.returncode,
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
            )
        except subprocess.TimeoutExpired:
            return ShellResult(
                command=' '.join(argv),
                returncode=124,
                stdout='',
                stderr=f'Command timed out after {self.timeout} seconds.',
            )
