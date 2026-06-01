# Poll the Gateway for local repair tasks

The local-first prototype uses a Repair Coordinator to poll the read-only
Observability Gateway for new backend and Flutter client issues. The
Coordinator stores repair tasks in SQLite, deduplicates them by issue ID, and
runs one repair task at a time in an isolated Git worktree.

Codex diagnoses and modifies product code. The Coordinator decides whether a
repair succeeded by strictly replaying a reviewed Flutter UI workload and
checking for new issues through the Gateway. A successful task creates a normal
GitHub pull request for human review but does not merge it.

## Consequences

- The Gateway remains read-only and stateless. It does not alert, schedule
  repairs, or persist task state.
- The Coordinator queries Sentry and Victoria data only through the Gateway.
- Polling is used before webhook delivery so backend and Flutter client issues
  share one trigger path.
- One issue ID creates at most one repair task unless an operator explicitly
  retries a failed task.
- Repairs run serially because Docker services and the Flutter App are shared
  local runtime resources.
- Each task uses a `codex/repair-<task-id>` branch and a separate Git worktree
  so automated edits do not modify the developer's active workspace.
- Flutter repairs relaunch the App from the task worktree and wait for a new VM
  target before hot restart, so validation executes the repaired Dart code.
- Codex may explore the Flutter UI while diagnosing a failure. Pull request
  creation requires a strict replay of an approved `*.hs.yaml` workload.
- The prototype reuses the developer machine's Git and `gh` authentication.
  A later version should use an isolated bot token.
