from pathlib import Path
from typing import Callable
from uuid import uuid4

from repair_coordinator.changes import ChangeGuard
from repair_coordinator.codex import CodexRunner
from repair_coordinator.evidence import EvidenceSnapshotWriter
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
        evidence: EvidenceSnapshotWriter | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._worktrees = worktrees
        self._codex = codex
        self._change_guard = change_guard
        self._restarter = restarter
        self._workloads = workloads
        self._pull_requests = pull_requests
        self._evidence = evidence or EvidenceSnapshotWriter(gateway)
        self._progress = progress

    @classmethod
    def from_environment(
        cls,
        store: RepairTaskStore,
        *,
        verbose: bool = False,
        progress: Callable[[str], None] | None = None,
    ) -> "RepairOrchestrator":
        """Create an orchestrator from local Coordinator configuration."""

        toolkit = ToolkitClient.from_environment()
        return cls(
            store=store,
            gateway=GatewayClient.from_environment(),
            worktrees=WorktreeManager.from_environment(),
            codex=CodexRunner.from_environment(verbose=verbose),
            change_guard=ChangeGuard(),
            restarter=ComponentRestarter.from_environment(toolkit, progress=progress),
            workloads=WorkloadRunner.from_environment(toolkit),
            pull_requests=PullRequestPublisher.from_environment(),
            progress=progress,
        )

    def process_next(self, *, workload_path: Path) -> dict[str, object] | None:
        """Repair, validate, and publish the next queued task."""

        task = self._store.claim_next()
        if task is None:
            return None
        self._report(f"claimed task {task['task_id']} for issue {task['issue_id']}")
        self._report(f"preparing worktree for task {task['task_id']}")
        prepared = self._worktrees.prepare(int(task["task_id"]))
        self._store.record_worktree(
            int(task["task_id"]),
            branch=str(prepared["branch"]),
            worktree_path=str(prepared["worktree_path"]),
        )
        self._report(
            f"prepared {prepared['branch']} at {prepared['worktree_path']}"
        )
        task = self._store.get_task(int(task["task_id"]))
        self._report("writing diagnostic evidence snapshot")
        self._evidence.write(task, progress=self._report)
        attempt_history: list[dict[str, object]] = []
        for attempt in range(1, 4):
            task = self._store.get_task(int(task["task_id"]))
            self._report(f"attempt {attempt}/3: restoring repair worktree")
            self._worktrees.restore_attempt_worktree(task)
            self._report(f"attempt {attempt}/3: invoking Codex")
            codex_result = self._codex.invoke(task, attempt=attempt)
            self._report(
                f"attempt {attempt}/3: Codex exited with "
                f"{codex_result['returncode']}"
            )
            changes = self._change_guard.check(task)
            self._report(
                f"attempt {attempt}/3: changed paths "
                f"{changes['changed_paths'] or 'none'}"
            )
            attempt_result: dict[str, object] = {
                "attempt": attempt,
                "codex_returncode": codex_result["returncode"],
                "codex_output": codex_result["output"],
                "codex_error_output": codex_result["error_output"],
                "changes": changes,
            }
            if not changes["valid"] or not changes["changed_paths"]:
                self._report(
                    f"attempt {attempt}/3: skipping validation because the diff "
                    "is invalid or empty"
                )
                attempt_history.append(attempt_result)
                self._store.record_attempt_history(int(task["task_id"]), attempt_history)
                continue

            try:
                self._report(f"attempt {attempt}/3: restarting changed components")
                self._restarter.restart(task, changes["changed_paths"])
                run_id = str(uuid4())
                self._report(
                    f"attempt {attempt}/3: replaying workload with run_id={run_id}"
                )
                validation = self._workloads.run(
                    workload_path,
                    run_id=run_id,
                    progress=self._workload_progress,
                )
                self._report(
                    f"attempt {attempt}/3: workload {validation['status']}"
                )
                self._report(
                    f"attempt {attempt}/3: checking diagnostics for run_id={run_id}"
                )
                new_issues = self._gateway.list_issues(run_id=run_id)
            except Exception as error:
                self._report(
                    f"attempt {attempt}/3 failed during execution: "
                    f"{type(error).__name__}: {error}"
                )
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
                self._report(
                    f"attempt {attempt}/3: validation passed and no new issues; "
                    "publishing pull request"
                )
                task = self._store.get_task(int(task["task_id"]))
                published = self._pull_requests.publish_report(
                    task, validation=validation
                )
                self._store.record_pr(int(task["task_id"]), pr_url=str(published["pr_url"]))
                self._report(f"published pull request {published['pr_url']}")
                return {
                    **published,
                    "attempts": attempt,
                    "validation_run_id": run_id,
                }
            self._report(
                f"attempt {attempt}/3 did not pass cleanly: "
                f"validation={validation['status']}, new_issues={len(new_issues)}"
            )

        self._report(f"task {task['task_id']} failed after 3 attempts")
        self._store.record_failed(int(task["task_id"]))
        return {
            "task_id": task["task_id"],
            "status": "failed",
            "attempts": 3,
            "attempt_history": attempt_history,
            "current_diff": self._change_guard.check(task),
        }

    def _workload_progress(self, message: str) -> None:
        self._report(f"workload: {message}")

    def _report(self, message: str) -> None:
        progress = getattr(self, "_progress", None)
        if progress is not None:
            progress(message)
