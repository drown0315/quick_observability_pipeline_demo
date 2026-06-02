import json
import sqlite3
from pathlib import Path


class RepairTaskStore:
    """SQLite storage for repair tasks discovered from Gateway issues.

    The store records one task per issue ID and its current status. Repeated
    polls keep the existing task instead of creating duplicate work.

    Example:
        Enqueuing `client:123` twice creates one task with status `queued`.
    """

    def __init__(self, database_path: Path) -> None:
        self._connection = sqlite3.connect(database_path)
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS repair_tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                branch TEXT,
                worktree_path TEXT,
                pr_url TEXT,
                attempt_history TEXT NOT NULL DEFAULT '[]'
            )
            """
        )

    def enqueue(self, issue: dict[str, object]) -> int:
        """Create one queued repair task unless the issue was already stored.

        Args:
            issue: Normalized Gateway issue summary. Its `issue_id` identifies
                the backend exception or Flutter client issue group.

        Returns:
            `1` when a queued task was created or `0` when the issue ID already
            has a task.

        Example:
            Enqueuing `{"issue_id": "client:123"}` for the first time returns
            `1`.
        """

        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO repair_tasks (issue_id, status)
            VALUES (?, 'queued')
            """,
            (issue["issue_id"],),
        )
        self._connection.commit()
        return cursor.rowcount

    def claim_next(self) -> dict[str, object] | None:
        """Move the oldest queued repair task to running state.

        Returns:
            Claimed task with its ID, issue ID, and `running` status. When no
            queued task remains, returns `None`.

        Example:
            Claiming the first task for `client:123` returns
            `{"task_id": 1, "issue_id": "client:123", "status": "running"}`.
        """

        self._connection.execute("BEGIN IMMEDIATE")
        row = self._connection.execute(
            """
            SELECT task_id, issue_id
            FROM repair_tasks
            WHERE status = 'queued'
            ORDER BY task_id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            self._connection.commit()
            return None

        self._connection.execute(
            "UPDATE repair_tasks SET status = 'running' WHERE task_id = ?",
            (row[0],),
        )
        self._connection.commit()
        return {"task_id": row[0], "issue_id": row[1], "status": "running"}

    def record_worktree(
        self, task_id: int, *, branch: str, worktree_path: str
    ) -> None:
        """Store the isolated Git workspace prepared for a running task.

        Args:
            task_id: Running repair task that owns the worktree.
            branch: Git branch created for automated repair changes.
            worktree_path: Absolute path where Codex will modify product code.

        Example:
            Recording task `1` stores branch `codex/repair-1` and its worktree
            path for later Codex execution.
        """

        cursor = self._connection.execute(
            """
            UPDATE repair_tasks
            SET branch = ?, worktree_path = ?
            WHERE task_id = ? AND status = 'running'
            """,
            (branch, worktree_path, task_id),
        )
        if cursor.rowcount != 1:
            self._connection.rollback()
            raise ValueError("worktree requires one running repair task")
        self._connection.commit()

    def get_task(self, task_id: int) -> dict[str, object]:
        """Return one repair task needed by later orchestration steps.

        Args:
            task_id: Stored repair task identifier.

        Returns:
            Task ID, issue ID, status, branch, and worktree path.

        Example:
            Looking up task `1` after worktree preparation returns its
            `codex/repair-1` branch and absolute worktree path.
        """

        row = self._connection.execute(
            """
            SELECT task_id, issue_id, status, branch, worktree_path, pr_url,
                   attempt_history
            FROM repair_tasks
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("repair task does not exist")
        return {
            "task_id": row[0],
            "issue_id": row[1],
            "status": row[2],
            "branch": row[3],
            "worktree_path": row[4],
            "pr_url": row[5],
            "attempt_history": json.loads(row[6]),
        }

    def record_attempt_history(
        self, task_id: int, attempt_history: list[dict[str, object]]
    ) -> None:
        """Store the validation history collected for one running task."""

        self._connection.execute(
            "UPDATE repair_tasks SET attempt_history = ? WHERE task_id = ?",
            (json.dumps(attempt_history), task_id),
        )
        self._connection.commit()

    def record_failed(self, task_id: int) -> None:
        """Mark one running task failed after its bounded attempts are exhausted."""

        self._connection.execute(
            "UPDATE repair_tasks SET status = 'failed' WHERE task_id = ?",
            (task_id,),
        )
        self._connection.commit()

    def record_pr(self, task_id: int, *, pr_url: str) -> None:
        """Mark one successfully published repair task with its pull request."""

        cursor = self._connection.execute(
            """
            UPDATE repair_tasks
            SET status = 'pr_created', pr_url = ?
            WHERE task_id = ? AND status = 'running'
            """,
            (pr_url, task_id),
        )
        if cursor.rowcount != 1:
            self._connection.rollback()
            raise ValueError("pull request requires one running repair task")
        self._connection.commit()

    def list_tasks(self) -> list[dict[str, str]]:
        """Return stored repair tasks ordered by issue ID."""

        rows = self._connection.execute(
            "SELECT issue_id, status FROM repair_tasks ORDER BY issue_id"
        )
        return [{"issue_id": row[0], "status": row[1]} for row in rows]

    def close(self) -> None:
        """Close the SQLite connection used by this store."""

        self._connection.close()
