# Repair Coordinator Acceptance

This guide validates the local Repair Coordinator from service startup through
issue discovery, bounded evidence lookup, Codex repair attempts, strict Flutter
UI replay, and pull request creation.

## Current Limitation

Backend issues can be filtered by workload `run_id`. Flutter Sentry client
issues cannot yet be filtered by `run_id`: the Gateway Sentry adapter currently
treats that argument as reserved until the Flutter App attaches a workload tag
and the adapter queries it.

As a result:

- backend repair-loop acceptance can be completed end to end
- Flutter UI failures can be reproduced and inspected through diagnostics
- automatic Flutter client success detection can be affected by Sentry issues
  created during the previous 15 minutes

## Prerequisites

Create local Sentry configuration:

```bash
cp .env.example .env
```

Fill in:

```env
SENTRY_DSN=...
SENTRY_AUTH_TOKEN=...
SENTRY_ORG=...
SENTRY_PROJECT=todo-flutter-macos
APP_RELEASE=dev-local
APP_ENVIRONMENT=local
```

Verify local tools:

```bash
gh auth status
codex --version
flutter-mcp-toolkit --version
```

## Start Services

Start the backend stack:

```bash
./scripts/start_local.sh
```

Start the Flutter App in another terminal:

```bash
./scripts/run_flutter.sh
```

Confirm Flutter MCP can reach the running App:

```bash
flutter-mcp-toolkit doctor --json
```

## Smoke Test

Use an isolated Coordinator state directory:

```bash
export REPAIR_COORDINATOR_STATE_ROOT=/tmp/repair-acceptance
./scripts/run_repair_coordinator.sh --max-polls 0
```

Expected output:

```json
{"polls":0,"created":0,"seen":0,"processed":[]}
```

## Replay A Normal Journey

Run a reviewed UI workload with a fresh UUID:

```bash
export REPAIR_COORDINATOR_DB_PATH=/tmp/repair-acceptance/tasks.db
RUN_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"

cd services/repair_coordinator
uv run python -m repair_coordinator run-workload \
  ../../harness/normal_todo_journey.hs.yaml \
  --run-id "$RUN_ID"
```

Expected result:

```json
{
  "name": "normal_todo_journey",
  "status": "passed"
}
```

## Reproduce And Inspect A Backend Failure

Run the reviewed mixed workload:

```bash
RUN_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"

uv run python -m repair_coordinator run-workload \
  ../../harness/mixed_user_workload.hs.yaml \
  --run-id "$RUN_ID"
```

The workload reaches the deterministic backend deletion failure before the
Flutter completion failure. Return to the repository root and query bounded
evidence:

```bash
cd ../..
./scripts/diagnostics issues --since 15m --run-id "$RUN_ID"
./scripts/diagnostics show backend:<uuid-from-the-list>
```

## Run One Automatic Repair Poll

Start one polling iteration:

```bash
export REPAIR_COORDINATOR_STATE_ROOT=/tmp/repair-acceptance
./scripts/run_repair_coordinator.sh --max-polls 1
```

Confirm:

- the new issue creates one SQLite repair task
- repeated polls do not create a duplicate task for the same `issue_id`
- the task uses `.repair_coordinator/worktrees/repair-<task-id>`
- Codex runs on branch `codex/repair-<task-id>`
- changes outside `app/lib/` and `services/todo_api/` are rejected
- repair stops after at most three attempts
- a successful repair pushes its branch and creates a normal pull request

Inspect stored tasks:

```bash
cd services/repair_coordinator
export REPAIR_COORDINATOR_DB_PATH=/tmp/repair-acceptance/tasks.db
uv run python -m repair_coordinator list-tasks
```

## TODO: Complete Flutter Client Acceptance

- [ ] Attach the workload `run_id` to Flutter Sentry client events.
- [ ] Filter Sentry client issue queries by `run_id` in the Gateway adapter.
- [ ] Add tests proving historical `client:<group-id>` issues do not fail a
      repaired Flutter validation run.
- [ ] Replay the complete mixed journey and verify the Flutter repair task
      creates a pull request without a new client issue.
