import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Callable

from repair_coordinator.changes import ChangeGuard
from repair_coordinator.codex import CodexRunner
from repair_coordinator.gateway import GatewayClient
from repair_coordinator.orchestration import RepairOrchestrator
from repair_coordinator.pull_requests import PullRequestPublisher
from repair_coordinator.tasks import RepairTaskStore
from repair_coordinator.worktrees import WorktreeManager
from repair_coordinator.workloads import WorkloadRunner


def build_parser() -> argparse.ArgumentParser:
    """Build the public Repair Coordinator command-line interface."""

    parser = argparse.ArgumentParser(description="Coordinate local repair tasks")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("poll-once", help="Discover and enqueue new issues once")
    run = commands.add_parser("run", help="Continuously discover and enqueue new issues")
    run.add_argument("--interval-seconds", default=10, type=float)
    run.add_argument("--max-polls", type=int)
    run.add_argument("--workload", type=Path)
    run.add_argument("--verbose", action="store_true")
    commands.add_parser("claim-next", help="Claim the next queued repair task")
    prepare_worktree = commands.add_parser(
        "prepare-worktree", help="Create an isolated branch and worktree for one task"
    )
    prepare_worktree.add_argument("task_id", type=int)
    invoke_codex = commands.add_parser(
        "invoke-codex", help="Run Codex for one prepared repair task"
    )
    invoke_codex.add_argument("task_id", type=int)
    invoke_codex.add_argument("--attempt", required=True, type=int)
    invoke_codex.add_argument("--verbose", action="store_true")
    run_workload = commands.add_parser(
        "run-workload", help="Strictly replay one reviewed Flutter UI workload"
    )
    run_workload.add_argument("workload_path", type=Path)
    run_workload.add_argument("--run-id", required=True)
    check_changes = commands.add_parser(
        "check-changes", help="Validate repair diff paths before publication"
    )
    check_changes.add_argument("task_id", type=int)
    publish_pr = commands.add_parser(
        "publish-pr", help="Commit, push, and open a pull request for one validated task"
    )
    publish_pr.add_argument("task_id", type=int)
    publish_pr.add_argument("--validation-report", required=True, type=Path)
    process_next = commands.add_parser(
        "process-next", help="Repair and validate the next queued task"
    )
    process_next.add_argument("--workload", required=True, type=Path)
    process_next.add_argument("--verbose", action="store_true")
    commands.add_parser("list-tasks", help="List stored repair tasks")
    return parser


def poll_once(
    gateway: GatewayClient, store: RepairTaskStore
) -> dict[str, int]:
    """Discover recent issues and enqueue tasks that were not already stored.

    Args:
        gateway: Read-only Gateway client used to list normalized issues.
        store: SQLite task store that deduplicates issue IDs.

    Returns:
        Number of issue summaries seen and queued tasks created by this poll.

    Example:
        Polling one new `client:123` issue returns `{"seen": 1, "created": 1}`.
    """

    issues = gateway.list_issues()
    return {
        "seen": len(issues),
        "created": sum(store.enqueue(issue) for issue in issues),
    }


def main() -> int:
    """Run one Repair Coordinator CLI command and print its JSON response."""

    args = build_parser().parse_args()
    if args.command == "run-workload":
        value = WorkloadRunner.from_environment().run(
            args.workload_path,
            run_id=args.run_id,
            progress=report_progress,
        )
        print(json.dumps(value))
        return 0

    store = RepairTaskStore(Path(os.environ["REPAIR_COORDINATOR_DB_PATH"]))
    try:
        if args.command == "poll-once":
            value: object = poll_once(GatewayClient.from_environment(), store)
        elif args.command == "run":
            value = run(
                args.interval_seconds,
                args.max_polls,
                args.workload,
                store,
                verbose=args.verbose,
                progress=report_progress,
            )
        elif args.command == "claim-next":
            value = store.claim_next()
        elif args.command == "prepare-worktree":
            value = WorktreeManager.from_environment().prepare(args.task_id)
            store.record_worktree(
                args.task_id,
                branch=str(value["branch"]),
                worktree_path=str(value["worktree_path"]),
            )
        elif args.command == "invoke-codex":
            value = CodexRunner.from_environment(verbose=args.verbose).invoke(
                store.get_task(args.task_id), attempt=args.attempt
            )
        elif args.command == "check-changes":
            value = ChangeGuard().check(store.get_task(args.task_id))
        elif args.command == "publish-pr":
            value = PullRequestPublisher.from_environment().publish(
                store.get_task(args.task_id),
                validation_report_path=args.validation_report,
            )
            store.record_pr(args.task_id, pr_url=str(value["pr_url"]))
        elif args.command == "process-next":
            value = RepairOrchestrator.from_environment(
                store, verbose=args.verbose, progress=report_progress
            ).process_next(
                workload_path=args.workload
            )
        else:
            value = store.list_tasks()
    finally:
        store.close()

    print(json.dumps(value))
    return 0


def run(
    interval_seconds: float,
    max_polls: int | None,
    workload_path: Path | None,
    store: RepairTaskStore,
    *,
    verbose: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Poll the Gateway repeatedly and return cumulative discovery counts.

    Args:
        interval_seconds: Delay between Gateway polls. `0` runs immediately and
            is useful for bounded local validation.
        max_polls: Optional number of polls to run before returning. When
            omitted, polling continues until the process is interrupted.
        workload_path: Optional reviewed UI workload. When present, each poll
            processes one queued repair task after issue discovery.
        store: SQLite task store shared by every poll.
        verbose: Whether to stream Codex stdout and stderr while each repair
            attempt runs. Output is still retained in the task result.

    Returns:
        Number of polls completed, issue summaries seen, and queued tasks
        created while the command was running.

    Example:
        `run(10, 2, None, store)` polls twice with a ten-second delay between
        calls.
    """

    report(progress, "repair coordinator starting")
    gateway = GatewayClient.from_environment()
    totals: dict[str, object] = {"polls": 0, "created": 0, "seen": 0}
    orchestrator = (
        RepairOrchestrator.from_environment(
            store,
            verbose=verbose,
            progress=progress,
        )
        if workload_path is not None
        else None
    )
    if orchestrator is not None:
        totals["processed"] = []
        report(progress, f"validation workload: {workload_path}")
    if max_polls is None:
        report(progress, f"polling every {interval_seconds:g}s until interrupted")
    else:
        report(
            progress,
            f"polling every {interval_seconds:g}s for {max_polls} poll(s)",
        )
    while max_polls is None or totals["polls"] < max_polls:
        report(progress, f"poll {totals['polls'] + 1}: querying diagnostics gateway")
        result = poll_once(gateway, store)
        totals["polls"] += 1
        totals["created"] += result["created"]
        totals["seen"] += result["seen"]
        report(
            progress,
            f"poll {totals['polls']}: saw {result['seen']} issue(s), "
            f"queued {result['created']} new task(s)",
        )
        if orchestrator is not None:
            processed = orchestrator.process_next(workload_path=workload_path)
            if processed is not None:
                totals["processed"].append(processed)
            else:
                report(progress, "no queued repair task to process")
        if max_polls is None or totals["polls"] < max_polls:
            report(progress, f"sleeping {interval_seconds:g}s before next poll")
            time.sleep(interval_seconds)
    return totals


def report_progress(message: str) -> None:
    """Print one progress line without contaminating the JSON stdout stream."""

    print(f"[repair-coordinator] {message}", file=sys.stderr, flush=True)


def report(progress: Callable[[str], None] | None, message: str) -> None:
    """Call one optional progress sink."""

    if progress is not None:
        progress(message)


if __name__ == "__main__":
    raise SystemExit(main())
