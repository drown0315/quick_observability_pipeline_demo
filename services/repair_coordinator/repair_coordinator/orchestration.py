from pathlib import Path
from uuid import uuid4

from repair_coordinator.changes import ChangeGuard
from repair_coordinator.codex import CodexRunner
from repair_coordinator.gateway import GatewayClient
from repair_coordinator.pull_requests import PullRequestPublisher
from repair_coordinator.restart import ComponentRestarter
from repair_coordinator.tasks import RepairTaskStore
from repair_coordinator.workloads import ToolkitClient, WorkloadRunner
from repair_coordinator.worktrees import WorktreeManager


class RepairOrchestrator:
    """Run bounded Codex repair attempts for queued diagnostic issues."""

    def __init__(
        self,
        store: RepairTaskStore,
        gateway: GatewayClient,
        worktrees: WorktreeManager,
        codex: CodexRunner,
        change_guard: ChangeGuard,
        restarter: ComponentRestarter,
        workloads: WorkloadRunner,
        pull_requests: PullRequestPublisher,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._worktrees = worktrees
        self._codex = codex
        self._change_guard = change_guard
        self._restarter = restarter
        self._workloads = workloads
        self._pull_requests = pull_requests

    @classmethod
    def from_environment(
        cls, store: RepairTaskStore, *, verbose: bool = False
    ) -> "RepairOrchestrator":
        """Create an orchestrator from local Coordinator configuration."""

        toolkit = ToolkitClient.from_environment()
        return cls(
            store=store,
            gateway=GatewayClient.from_environment(),
            worktrees=WorktreeManager.from_environment(),
            codex=CodexRunner.from_environment(verbose=verbose),
            change_guard=ChangeGuard(),
            restarter=ComponentRestarter.from_environment(toolkit),
            workloads=WorkloadRunner.from_environment(toolkit),
            pull_requests=PullRequestPublisher.from_environment(),
        )

    def process_next(self, *, workload_path: Path) -> dict[str, object] | None:
        """Repair, validate, and publish the next queued task."""

        task = self._store.claim_next()
        if task is None:
            return None
        prepared = self._worktrees.prepare(int(task["task_id"]))
        self._store.record_worktree(
            int(task["task_id"]),
            branch=str(prepared["branch"]),
            worktree_path=str(prepared["worktree_path"]),
        )
        attempt_history: list[dict[str, object]] = []
        for attempt in range(1, 4):
            task = self._store.get_task(int(task["task_id"]))
            codex_result = self._codex.invoke(task, attempt=attempt)
            changes = self._change_guard.check(task)
            attempt_result: dict[str, object] = {
                "attempt": attempt,
                "codex_returncode": codex_result["returncode"],
                "codex_output": codex_result["output"],
                "codex_error_output": codex_result["error_output"],
                "changes": changes,
            }
            if not changes["valid"] or not changes["changed_paths"]:
                attempt_history.append(attempt_result)
                self._store.record_attempt_history(int(task["task_id"]), attempt_history)
                continue

            try:
                self._restarter.restart(task, changes["changed_paths"])
                run_id = str(uuid4())
                validation = self._workloads.run(workload_path, run_id=run_id)
                new_issues = self._gateway.list_issues(run_id=run_id)
            except Exception as error:
                attempt_result["execution_error"] = {
                    "type": type(error).__name__,
                    "message": str(error),
                }
                attempt_history.append(attempt_result)
                self._store.record_attempt_history(int(task["task_id"]), attempt_history)
                continue
            attempt_result.update(
                {"run_id": run_id, "validation": validation, "new_issues": new_issues}
            )
            attempt_history.append(attempt_result)
            self._store.record_attempt_history(int(task["task_id"]), attempt_history)
            if validation["status"] == "passed" and not new_issues:
                task = self._store.get_task(int(task["task_id"]))
                published = self._pull_requests.publish_report(
                    task, validation=validation
                )
                self._store.record_pr(int(task["task_id"]), pr_url=str(published["pr_url"]))
                return {
                    **published,
                    "attempts": attempt,
                    "validation_run_id": run_id,
                }

        self._store.record_failed(int(task["task_id"]))
        return {
            "task_id": task["task_id"],
            "status": "failed",
            "attempts": 3,
            "attempt_history": attempt_history,
            "current_diff": self._change_guard.check(task),
        }
