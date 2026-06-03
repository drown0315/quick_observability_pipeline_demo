import subprocess


class ChangeGuard:
    """Validate repair-task Git changes against editable product paths.

    The guard reads tracked and untracked changes from one task worktree.
    Automatic repairs may modify Flutter product code in `app/lib/` or backend
    product code in `services/todo_api/`.

    Example:
        A change to `harness/mixed_user_workload.hs.yaml` returns `valid: false`.
    """

    _allowed_prefixes = ("app/lib/", "services/todo_api/")
    _ignored_prefixes = (".repair/",)

    def check(self, task: dict[str, object]) -> dict[str, object]:
        """Return changed paths and any files outside the repair whitelist.

        Args:
            task: Prepared repair task containing its absolute worktree path.

        Returns:
            Validation status, every changed path, and paths outside editable
            product directories.

        Example:
            Editing only `app/lib/main.dart` returns an empty
            `disallowed_paths` list.
        """

        worktree_path = task.get("worktree_path")
        if not worktree_path:
            raise ValueError("change validation requires one prepared task")
        changed_paths = [
            path
            for path in self._changed_paths(str(worktree_path))
            if not path.startswith(self._ignored_prefixes)
        ]
        disallowed_paths = [
            path
            for path in changed_paths
            if not path.startswith(self._allowed_prefixes)
        ]
        return {
            "valid": not disallowed_paths,
            "changed_paths": changed_paths,
            "disallowed_paths": disallowed_paths,
        }

    @staticmethod
    def _changed_paths(worktree_path: str) -> list[str]:
        """Return sorted tracked and untracked paths from one Git worktree."""

        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            check=True,
            capture_output=True,
            cwd=worktree_path,
            text=True,
        )
        entries = result.stdout.split("\0")
        paths: list[str] = []
        index = 0
        while index < len(entries):
            entry = entries[index]
            if not entry:
                break
            status = entry[:2]
            paths.append(entry[3:])
            index += 2 if "R" in status or "C" in status else 1
        return sorted(paths)
