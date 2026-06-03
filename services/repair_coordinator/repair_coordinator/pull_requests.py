import json
import os
from pathlib import Path
import shlex
import subprocess

from repair_coordinator.changes import ChangeGuard


class PullRequestPublisher:
    """Publish validated repair changes as one normal GitHub pull request.

    The publisher contains the local `gh` command and a diff guard. It commits
    only whitelisted product-code changes, pushes the repair branch, and opens
    a pull request without merging it.

    Example:
        Publishing task `1` pushes `codex/repair-1` and returns its PR URL.
    """

    def __init__(self, gh_command: list[str], change_guard: ChangeGuard) -> None:
        self._gh_command = gh_command
        self._change_guard = change_guard

    @classmethod
    def from_environment(cls) -> "PullRequestPublisher":
        """Create a publisher from local GitHub CLI configuration."""

        return cls(
            gh_command=shlex.split(os.environ.get("REPAIR_GH_COMMAND", "gh")),
            change_guard=ChangeGuard(),
        )

    def publish(
        self,
        task: dict[str, object],
        *,
        validation_report_path: Path,
    ) -> dict[str, object]:
        """Commit, push, and open a PR for one validated repair task.

        Args:
            task: Running repair task with its issue ID, branch, and worktree.
            validation_report_path: JSON report produced by strict workload
                replay. Publication requires its status to be `passed`.

        Returns:
            Task ID, `pr_created` status, and GitHub pull request URL.

        Example:
            A passed `mixed_user_workload` report publishes the current repair
            branch as a normal pull request.
        """

        return self.publish_report(
            task, validation=json.loads(validation_report_path.read_text())
        )

    def publish_report(
        self, task: dict[str, object], *, validation: dict[str, object]
    ) -> dict[str, object]:
        """Publish one task after strict workload replay passed."""

        if validation.get("status") != "passed":
            raise ValueError("pull request requires a passed workload report")
        changes = self._change_guard.check(task)
        if not changes["valid"] or not changes["changed_paths"]:
            raise ValueError("pull request requires a non-empty whitelisted diff")

        worktree_path = str(task["worktree_path"])
        branch = str(task["branch"])
        issue_id = str(task["issue_id"])
        self._git(worktree_path, "add", "--all", "--", *changes["changed_paths"])
        self._git(worktree_path, "commit", "-m", f"Repair {issue_id}")
        self._git(worktree_path, "push", "--set-upstream", "origin", branch)
        body = (
            f"Automated repair for `{issue_id}`.\n\n"
            f"Validated with `{validation['name']}` using run ID "
            f"`{validation['run_id']}`.\n\n"
            f"Attempts: {len(task['attempt_history'])}.\n\n"
            "Changed files:\n"
            + "\n".join(f"- `{path}`" for path in changes["changed_paths"])
        )
        result = subprocess.run(
            [
                *self._gh_command,
                "pr",
                "create",
                "--head",
                branch,
                "--title",
                f"Repair {issue_id}",
                "--body",
                body,
            ],
            check=True,
            capture_output=True,
            cwd=worktree_path,
            text=True,
        )
        return {
            "task_id": task["task_id"],
            "status": "pr_created",
            "pr_url": result.stdout.strip(),
        }

    @staticmethod
    def _git(worktree_path: str, *arguments: str) -> None:
        """Run one required Git command inside a repair worktree."""

        subprocess.run(
            ["git", *arguments],
            check=True,
            capture_output=True,
            cwd=worktree_path,
            text=True,
        )
