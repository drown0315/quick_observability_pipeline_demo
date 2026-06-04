# Quick Observability Pipeline Demo

This is a local-first demo for an automated Codex repair loop.

The demo app is a Flutter Todo App backed by FastAPI and SQLite. The current
demo has only been tested by running the Flutter app on macOS. The app includes
a small script that clicks through the UI and intentionally triggers a bug. When
that bug happens, the observability stack captures the failure evidence and a
local repair process asks Codex to fix the product code.

## Demo Flow

This demo intentionally includes deterministic escaped bugs:

- Deleting a Todo whose title contains `crash` raises a backend
  `RuntimeError("todo deletion failed")`.
- Completing a Todo whose title contains `mobile-crash` raises a Flutter
  `StateError("todo completion failed")`.

The click-through script creates normal Todos first, then creates a Todo named
`backend-crash-<run_id>` and tries to delete it. That action triggers the
backend issue. The point of the demo is that Codex sees the failure through
logs, traces, metrics, and error events instead of a hard-coded test
expectation.

### Concept

The original idea is to give Codex a queryable observability stack. Codex does
not guess from a failed UI alone; it queries logs, metrics, and traces, repairs
the codebase, restarts the app, and re-runs the same scripted app interaction.

![Codex automatic repair loop concept](docs/assets/codex-auto-repair-loop.svg)

### This Demo

This repository uses a hybrid stack. The Flutter App sends client exceptions to
Sentry. The FastAPI backend sends logs, metrics, and traces through the
OpenTelemetry Collector into Victoria services. The Observability Gateway reads
both Sentry and Victoria and exposes one diagnostics API to Codex.

The Flutter App does not send logs, metrics, or traces directly into the
Victoria stack. It reaches that stack indirectly by calling the FastAPI backend,
which emits backend telemetry.

![Demo observability topology](docs/assets/demo-observability-topology.svg)

The demo has three local helpers:

- **Click-through script**: a saved set of Flutter App actions, such as typing a
  Todo title, pressing Add, and pressing Delete. In the code this is called a
  workload.
- **Diagnostics Gateway**: a read-only local API that gathers the relevant
  Sentry and Victoria evidence for Codex.
- **Repair Coordinator**: a local repair process that watches for new issues,
  starts Codex, validates the repair, and opens a pull request.

The automatic repair loop works like this:

1. Start the backend services and the Flutter App.
2. Start the Repair Coordinator. It checks the Diagnostics Gateway for recent
   failures.
3. Run the click-through script. It creates a Todo that triggers the injected
   backend crash.
4. The Flutter App and FastAPI backend emit diagnostic signals.
5. The Diagnostics Gateway collects the relevant Sentry event, backend logs,
   traces, and metrics into a small evidence bundle.
6. The Repair Coordinator creates a repair branch and starts Codex on that
   branch.
7. Codex reads the evidence, finds the product bug, and edits the app or API
   code.
8. The Repair Coordinator restarts the changed component and runs the same
   click-through script again.
9. If the scripted app interaction now passes and no new issue appears, the
   Coordinator creates a pull request for the repair.

### Final Result

The final result is an automatically generated repair pull request. In the demo
run, Codex repaired `client:7520855204`, validated the fix with the
`mixed_user_workload` workload, and opened PR `#27` from branch
`codex/repair-1-4` into `main`.

The generated PR records the repair summary, validation run ID, number of
attempts, and changed files so a maintainer can review the Codex-authored bug
fix before merging it.

![Codex-generated repair pull request](docs/assets/automated-repair-pr.png)

## Run Automatic Repair

These commands use the Flutter macOS desktop target. That is the only demo
runtime tested so far.

### Prerequisites

Install and configure these local tools before running the full repair loop:

- Docker Desktop, or another Docker runtime with `docker compose`, for the
  FastAPI backend, OpenTelemetry Collector, VictoriaLogs, VictoriaMetrics, and
  VictoriaTraces.
- Flutter with macOS desktop support, plus the required Xcode/macOS build
  tooling.
- `uv`, used to run the Python services and workload runner.
- `flutter-mcp-toolkit`, used by the workload runner and Repair Coordinator to
  drive the running Flutter App through semantic UI actions.
- Codex CLI, used by the Repair Coordinator to invoke local repair attempts.
- GitHub CLI (`gh`) authenticated for the repository, required only when the
  Coordinator reaches the pull request creation step.

Quick local tool check:

```bash
docker compose version
flutter doctor
uv --version
flutter-mcp-toolkit --version
codex --version
gh auth status
```

The app must be run as a Flutter macOS debug app. The workload runner talks to
that running app through `flutter-mcp-toolkit`; it does not click screen
coordinates directly.

### Sentry Configuration

Create local configuration:

```bash
cp .env.example .env
```

Fill in the Sentry fields:

```env
SENTRY_DSN=...
SENTRY_AUTH_TOKEN=...
SENTRY_ORG=...
SENTRY_PROJECT=todo-flutter-macos
APP_RELEASE=dev-local
APP_ENVIRONMENT=local
```

Use one Sentry SaaS project for Flutter macOS client exceptions. The default
project slug is `todo-flutter-macos`, but it can be changed with
`SENTRY_PROJECT`.

Field usage:

- `SENTRY_DSN`: passed to the Flutter App so client exceptions are sent to
  Sentry.
- `SENTRY_AUTH_TOKEN`: read-only Sentry API token for the local Diagnostics
  Gateway. It needs `event:read`. The token is not passed to the Flutter
  process.
- `SENTRY_ORG`: Sentry organization slug used by the Gateway API client.
- `SENTRY_PROJECT`: Sentry project slug used by the Gateway API client.
- `APP_RELEASE` and `APP_ENVIRONMENT`: passed to Flutter and used to separate
  local demo events from other runs.

### Start The Demo

Terminal 1: start the backend, Diagnostics Gateway, and observability services.

```bash
./scripts/start_local.sh
```

Terminal 2: start the Flutter macOS App.

```bash
./scripts/run_flutter.sh
```

In another terminal, confirm the Flutter MCP toolkit can see the running app:

```bash
flutter-mcp-toolkit doctor --json
```

Terminal 3: start the Repair Coordinator. This is the local repair process that
watches for failures, runs Codex, validates the fix, and creates a pull
request.

```bash
./scripts/run_repair_coordinator.sh --verbose
```

Terminal 4: trigger the injected issue by running the click-through script.

```bash
RUN_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
cd services/repair_coordinator
uv run python -m repair_coordinator run-workload \
  ../../harness/mixed_user_workload.hs.yaml \
  --run-id "$RUN_ID"
```

Stop the local stack when finished.

```bash
cd ../..
./scripts/stop_local.sh
```

## More Detail

- [Prototype Scope](docs/PROTOTYPE-SCOPE.md)
- [Repair Coordinator Acceptance](docs/REPAIR-COORDINATOR-ACCEPTANCE.md)
- [ADR 0001: Hybrid Observability Pipeline](docs/adr/0001-hybrid-observability-pipeline.md)
- [ADR 0002: Poll Gateway for Local Repair Tasks](docs/adr/0002-poll-gateway-for-local-repair-tasks.md)
