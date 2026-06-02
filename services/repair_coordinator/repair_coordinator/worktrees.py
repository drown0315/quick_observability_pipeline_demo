import os
from pathlib import Path
import subprocess


class WorktreeManager:
    """Create isolated Git worktrees for running repair tasks.

    The manager contains the source repository and the directory where repair
    worktrees are created. Each task receives a `codex/repair-<task-id>` branch.

    Example:
        Preparing task `1` creates branch `codex/repair-1` in worktree
        `/tmp/repair-worktrees/repair-1`.
    """

    def __init__(self, repository_root: Path, worktree_root: Path) -> None:
        self._repository_root = repository_root
        self._worktree_root = worktree_root

    @classmethod
    def from_environment(cls) -> "WorktreeManager":
        """Create a worktree manager from local Coordinator configuration."""

        return cls(
            repository_root=Path(os.environ["REPAIR_REPOSITORY_ROOT"]),
            worktree_root=Path(os.environ["REPAIR_WORKTREE_ROOT"]),
        )

    def prepare(self, task_id: int) -> dict[str, object]:
        """Create one repair branch and worktree for a task.

        Args:
            task_id: Repair task identifier used in the branch and directory
                names.

        Returns:
            Task ID, created branch name, and absolute worktree path.

        Example:
            `prepare(1)` creates `codex/repair-1` and returns its worktree path.
        """

        branch, worktree_path = self._available_destination(task_id)
        self._worktree_root.mkdir(parents=True, exist_ok=True)
        self._run_git(
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            "HEAD",
        )
        return {
            "task_id": task_id,
            "branch": branch,
            "worktree_path": str(worktree_path),
        }

    def _available_destination(self, task_id: int) -> tuple[str, Path]:
        """Return an unused repair branch and worktree path for one task."""

        base_branch = f"codex/repair-{task_id}"
        base_path = self._worktree_root / f"repair-{task_id}"
        for suffix in ["", *[f"-{index}" for index in range(2, 100)]]:
            branch = f"{base_branch}{suffix}"
            worktree_path = Path(f"{base_path}{suffix}")
            if not self._branch_exists(branch) and not worktree_path.exists():
                return branch, worktree_path
        raise RuntimeError(f"no available repair worktree destination for task {task_id}")

    def _branch_exists(self, branch: str) -> bool:
        """Return whether Git already has one local branch."""

        result = self._run_git(
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}",
            check=False,
        )
        return result.returncode == 0

    def _run_git(
        self, *arguments: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        """Run one Git command in the source repository and preserve stderr."""

        result = subprocess.run(
            ["git", "-C", str(self._repository_root), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            stderr = result.stderr.strip() or "(no stderr)"
            stdout = result.stdout.strip() or "(no stdout)"
            raise RuntimeError(
                "git command failed: "
                f"git -C {self._repository_root} {' '.join(arguments)}\n"
                f"stdout: {stdout}\n"
                f"stderr: {stderr}"
            )
        return result
