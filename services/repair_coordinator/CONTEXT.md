# Repair Coordinator

Local orchestration service that turns bounded Gateway issues into isolated
Codex repair attempts, strict Flutter UI workload replay, and normal GitHub pull
requests.

## Key Files

- `repair_coordinator/__main__.py` - public CLI commands and poll loop.
- `repair_coordinator/orchestration.py` - end-to-end repair attempt flow.
- `repair_coordinator/tasks.py` - SQLite task queue, status transitions, and attempt history.
- `repair_coordinator/gateway.py` - read-only issue discovery through the Observability Gateway.
- `repair_coordinator/worktrees.py` - per-task `codex/repair-<task-id>` branches and Git worktrees.
- `repair_coordinator/codex.py` - bounded repair prompt and Codex subprocess invocation.
- `repair_coordinator/changes.py` - product-code diff whitelist before restart, validation, or publication.
- `repair_coordinator/restart.py` - restart only changed local components before workload replay.
- `repair_coordinator/workloads.py` - reviewed YAML workload replay through Flutter MCP semantic widgets.
- `repair_coordinator/pull_requests.py` - commit, push, and open a non-merged GitHub pull request.
- `tests/` - CLI, orchestration, restart, diff guard, and workload runner coverage.

## Workflow

The normal loop is:

1. poll `GET /diagnostics/issues` through `GatewayClient`
2. enqueue one task per unique `issue_id`
3. prepare an isolated Git worktree
4. invoke Codex for at most three repair attempts
5. reject empty or non-whitelisted diffs
6. restart affected local components
7. replay one reviewed Flutter MCP workload with a fresh `run_id`
8. check the Gateway for issues from that validation run
9. publish a PR only after workload replay passes and no new run issues appear

## Constraints

- Do not query Sentry, Victoria, or product APIs directly from this service;
  diagnostics enter through the Gateway.
- Keep automatic edits limited to `app/lib/` and `services/todo_api/`.
- Treat `harness/`, `services/observability_gateway/`, `observability/`,
  `docker-compose.yml`, and `scripts/diagnostics` as protected validation or
  observability paths.
- Validate user-visible behavior through reviewed Flutter UI workloads. Do not
  replace workload replay with direct backend calls or coordinate clicks.
- Keep repair attempts bounded. The orchestrator currently stops after three
  attempts and records attempt history.
- Pull request publication is the terminal successful state; the Coordinator
  opens normal PRs and does not merge them.

## Runtime State

- `REPAIR_COORDINATOR_DB_PATH` points at the SQLite task database.
- `.repair_coordinator/tasks.db` is local runtime state, not source context.
- Repair worktrees are created under `REPAIR_WORKTREE_ROOT`; do not treat them
  as canonical source files.

## Configuration

- Gateway: `DIAGNOSTICS_GATEWAY_URL`
- Repository/worktrees: `REPAIR_REPOSITORY_ROOT`, `REPAIR_WORKTREE_ROOT`
- Tooling commands: `REPAIR_CODEX_COMMAND`, `FLUTTER_MCP_TOOLKIT_COMMAND`,
  `REPAIR_DOCKER_COMMAND`, `REPAIR_GH_COMMAND`
- Codex permissions: `REPAIR_CODEX_SANDBOX` selects the sandbox passed to
  `codex exec`. The demo runner defaults it to `workspace-write`. Before Codex
  runs, the Coordinator queries the local Diagnostics Gateway and writes the
  bounded issue detail to `.repair/evidence.json` inside the repair worktree.
- Restart options: `REPAIR_COMPOSE_PROJECT_NAME`, `REPAIR_COMPOSE_ENV_FILE`,
  `REPAIR_FLUTTER_LAUNCH_COMMAND`
