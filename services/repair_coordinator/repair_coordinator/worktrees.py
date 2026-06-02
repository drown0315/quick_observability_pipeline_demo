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

        branch = f"codex/repair-{task_id}"
        worktree_path = self._worktree_root / f"repair-{task_id}"
        self._worktree_root.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self._repository_root),
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree_path),
                "HEAD",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return {
            "task_id": task_id,
            "branch": branch,
            "worktree_path": str(worktree_path),
        }
