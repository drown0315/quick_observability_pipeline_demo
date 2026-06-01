import os
import shlex
import subprocess


class CodexRunner:
    """Invoke Codex inside an isolated repair-task worktree.

    The runner contains the local Codex command. It supplies the issue ID,
    diagnostics entry point, editable product paths, and protected validation
    paths in one repair prompt.

    Example:
        Invoking task `1` runs `codex exec` against its prepared worktree.
    """

    def __init__(self, command: list[str]) -> None:
        self._command = command

    @classmethod
    def from_environment(cls) -> "CodexRunner":
        """Create a Codex runner from local Coordinator configuration."""

        return cls(shlex.split(os.environ.get("REPAIR_CODEX_COMMAND", "codex")))

    def invoke(self, task: dict[str, object], *, attempt: int) -> dict[str, object]:
        """Run Codex once for a prepared repair task.

        Args:
            task: Running repair task with an issue ID and prepared worktree
                path.
            attempt: One-based repair attempt number included in the prompt.

        Returns:
            Task ID, attempt number, Codex process exit code, and stdout.

        Example:
            Invoking task `1` on its first attempt returns the Codex process
            result for the `codex/repair-1` worktree.
        """

        worktree_path = task.get("worktree_path")
        if task.get("status") != "running" or not worktree_path:
            raise ValueError("Codex invocation requires one prepared running task")

        result = subprocess.run(
            [
                *self._command,
                "exec",
                "-C",
                str(worktree_path),
                "--sandbox",
                "workspace-write",
                "--ask-for-approval",
                "never",
                self._prompt(issue_id=str(task["issue_id"]), attempt=attempt),
            ],
            check=False,
            capture_output=True,
            cwd=str(worktree_path),
            text=True,
        )
        return {
            "task_id": task["task_id"],
            "attempt": attempt,
            "returncode": result.returncode,
            "output": result.stdout,
        }

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
