import os
from pathlib import Path
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

    def __init__(
        self,
        command: list[str],
        *,
        sandbox: str = "workspace-write",
        verbose: bool = False,
    ) -> None:
        self._command = command
        self._sandbox = sandbox
        self._verbose = verbose

    @classmethod
    def from_environment(cls, *, verbose: bool = False) -> "CodexRunner":
        """Create a Codex runner from local Coordinator configuration."""

        return cls(
            shlex.split(os.environ.get("REPAIR_CODEX_COMMAND", "codex")),
            sandbox=os.environ.get("REPAIR_CODEX_SANDBOX", "workspace-write"),
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
            self._sandbox,
            self._prompt(issue_id=str(task["issue_id"]), attempt=attempt),
        ]
        environment = self._environment()
        result = (
            self._run_verbose(command, cwd=str(worktree_path), env=environment)
            if self._verbose
            else subprocess.run(
                command,
                check=False,
                capture_output=True,
                cwd=str(worktree_path),
                env=environment,
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
        command: list[str], *, cwd: str, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        """Run Codex while forwarding and retaining each output line."""

        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
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
    def _environment() -> dict[str, str]:
        """Return the Codex process environment with compose variables loaded."""

        environment = os.environ.copy()
        env_file = os.environ.get("REPAIR_COMPOSE_ENV_FILE")
        if env_file:
            for key, value in CodexRunner._read_env_file(Path(env_file)).items():
                if not environment.get(key):
                    environment[key] = value
        return environment

    @staticmethod
    def _read_env_file(path: Path) -> dict[str, str]:
        """Read simple KEY=VALUE assignments from one dotenv-style file."""

        if not path.exists():
            return {}
        values: dict[str, str] = {}
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.removeprefix("export ").strip()
            if not key:
                continue
            values[key] = CodexRunner._parse_env_value(value.strip())
        return values

    @staticmethod
    def _parse_env_value(value: str) -> str:
        """Return one dotenv value without surrounding shell quotes."""

        if not value:
            return ""
        try:
            parsed = shlex.split(value, comments=False, posix=True)
        except ValueError:
            return value
        return parsed[0] if len(parsed) == 1 else value

    @staticmethod
    def _prompt(*, issue_id: str, attempt: int) -> str:
        """Build the bounded instructions for one Codex repair attempt."""

        return f"""Repair issue {issue_id}. This is attempt {attempt} of at most 3.

Read bounded diagnostic evidence from .repair/evidence.json before editing.
Modify product code only in:
- app/lib/
- services/todo_api/

Do not modify protected validation or observability paths:
- harness/
- services/observability_gateway/
- observability/
- docker-compose.yml
- scripts/diagnostics

Diagnose the issue and make the smallest product-code repair. Do not restart
components yourself; the Coordinator validation flow restarts affected services
after your diff is checked. Do not run a bare `docker compose` command from the
repair worktree. If manual compose inspection is unavoidable, pass the
`REPAIR_COMPOSE_ENV_FILE` environment variable to Docker Compose with
`--env-file` so the root repository `.env` is used.
"""
