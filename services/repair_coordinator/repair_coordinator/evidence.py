import json
from pathlib import Path
from typing import Callable

from repair_coordinator.gateway import GatewayClient


class EvidenceSnapshotWriter:
    """Writer for local diagnostic snapshots used by Codex repair attempts.

    It contains the read-only Gateway client and writes one JSON file inside
    the prepared repair worktree.

    Example:
        Writing task `1` with issue `client:123` creates
        `.repair/evidence.json` inside that task's worktree.
    """

    def __init__(self, gateway: GatewayClient) -> None:
        self._gateway = gateway

    def write(
        self,
        task: dict[str, object],
        *,
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        """Fetch Gateway issue detail and write it into the repair worktree.

        Args:
            task: Running repair task with an issue ID and prepared worktree
                path. The method raises `ValueError` when either value is
                missing.
            progress: Optional sink for a short status message after the file
                is written.

        Returns:
            Absolute path to the JSON snapshot written for this task.

        Example:
            A task whose worktree is `/tmp/repair-1` writes
            `/tmp/repair-1/.repair/evidence.json`.
        """

        issue_id = task.get("issue_id")
        worktree_path = task.get("worktree_path")
        if not issue_id or not worktree_path:
            raise ValueError("Evidence snapshot requires an issue ID and worktree path")

        detail = self._gateway.get_issue(str(issue_id))
        snapshot_path = Path(str(worktree_path)) / ".repair" / "evidence.json"
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "issue_id": str(issue_id),
            "source": "diagnostics_gateway",
            "detail": detail,
        }
        snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        if progress is not None:
            progress(f"wrote diagnostic evidence snapshot to {snapshot_path}")
        return snapshot_path
