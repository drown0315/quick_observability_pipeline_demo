import os
import shlex
import subprocess
import sys
from threading import Thread
from typing import TextIO


class CodexRunner:
    """Invoke Codex inside an isolated repair-task worktree.

    The runner contains the local Codex command and whether verbose output is
    enabled. It supplies the issue ID, diagnostics entry point, editable
    product paths, and protected validation paths in one repair prompt.

    Example:
        Invoking task `1` runs `codex exec` against its prepared worktree.
    """

    def __init__(self, command: list[str], *, verbose: bool = False) -> None:
        self._command = command
        self._verbose = verbose

    @classmethod
    def from_environment(cls, *, verbose: bool = False) -> "CodexRunner":
        """Create a Codex runner from local Coordinator configuration."""

        return cls(
            shlex.split(os.environ.get("REPAIR_CODEX_COMMAND", "codex")),
            verbose=verbose,
        )

    def invoke(self, task: dict[str, object], *, attempt: int) -> dict[str, object]:
        """Run Codex once for a prepared repair task.

        Args:
            task: Running repair task with an issue ID and prepared worktree
                path.
            attempt: One-based repair attempt number included in the prompt.

        Returns:
            Task ID, attempt number, Codex process exit code, stdout, and
            stderr. Verbose mode also forwards stdout and stderr to the
            Coordinator terminal while Codex runs.

        Example:
            Invoking task `1` on its first attempt returns the Codex process
            result for the `codex/repair-1` worktree.
        """

        worktree_path = task.get("worktree_path")
        if task.get("status") != "running" or not worktree_path:
            raise ValueError("Codex invocation requires one prepared running task")

        command = [
            *self._command,
            "--ask-for-approval",
            "never",
            "exec",
            "-C",
            str(worktree_path),
            "--sandbox",
            "workspace-write",
            self._prompt(issue_id=str(task["issue_id"]), attempt=attempt),
        ]
        result = (
            self._run_verbose(command, cwd=str(worktree_path))
            if self._verbose
            else subprocess.run(
                command,
                check=False,
                capture_output=True,
                cwd=str(worktree_path),
                text=True,
            )
        )
        return {
            "task_id": task["task_id"],
            "attempt": attempt,
            "returncode": result.returncode,
            "output": result.stdout,
            "error_output": result.stderr,
        }

    @staticmethod
    def _run_verbose(
        command: list[str], *, cwd: str
    ) -> subprocess.CompletedProcess[str]:
        """Run Codex while forwarding and retaining each output line."""

        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout: list[str] = []
        stderr: list[str] = []
        threads = [
            Thread(
                target=CodexRunner._forward_lines,
                args=(process.stdout, sys.stdout, stdout),
            ),
            Thread(
                target=CodexRunner._forward_lines,
                args=(process.stderr, sys.stderr, stderr),
            ),
        ]
        for thread in threads:
            thread.start()
        returncode = process.wait()
        for thread in threads:
            thread.join()
        return subprocess.CompletedProcess(
            command,
            returncode,
            stdout="".join(stdout),
            stderr="".join(stderr),
        )

    @staticmethod
    def _forward_lines(
        source: TextIO | None, destination: TextIO, captured: list[str]
    ) -> None:
        """Forward one subprocess stream line by line and retain its content."""

        if source is None:
            return
        for line in source:
            captured.append(line)
            destination.write(line)
            destination.flush()

    @staticmethod
    def _prompt(*, issue_id: str, attempt: int) -> str:
        """Build the bounded instructions for one Codex repair attempt."""

        return f"""Repair issue {issue_id}. This is attempt {attempt} of at most 3.

Query bounded diagnostic evidence through scripts/diagnostics before editing.
Modify product code only in:
- app/lib/
- services/todo_api/

Do not modify protected validation or observability paths:
- harness/
- services/observability_gateway/
- observability/
- docker-compose.yml
- scripts/diagnostics

Diagnose the issue, make the smallest product-code repair, restart only affected
components, and report the evidence used and validation performed.
"""
