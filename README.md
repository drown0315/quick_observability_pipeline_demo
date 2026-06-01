# Quick Observability Pipeline Demo

A validation prototype for an automated Codex repair loop. A Flutter macOS Todo
App and its FastAPI backend emit diagnostic signals, Codex queries a single
local diagnostics entry point, repairs product code, and replays the same UI
journey to verify the fix.

## Architecture

```text
Flutter macOS App -> Sentry SaaS
Flutter macOS App -> FastAPI + SQLite
FastAPI -> OpenTelemetry Collector
        -> VictoriaLogs / VictoriaTraces / VictoriaMetrics
Codex -> diagnostics CLI -> Observability Gateway -> Sentry and Victoria APIs
Repair Coordinator -> Observability Gateway -> Codex -> validated pull request
```

The first version is intentionally local-first. It validates two escaped-bug
scenarios: an unexpected backend deletion failure and an unexpected Flutter
completion failure. UI journeys are driven through Flutter MCP tooling so the
feedback loop exercises real user behavior rather than direct API shortcuts.

## Status

The first Todo CRUD slice is implemented. It includes a Flutter macOS App,
FastAPI service, SQLite storage, and Docker Compose volume for local
persistence. Further observability work is tracked as GitHub issues.

See [Prototype Scope](docs/PROTOTYPE-SCOPE.md) and
[ADR 0001](docs/adr/0001-hybrid-observability-pipeline.md). Use
[Repair Coordinator Acceptance](docs/REPAIR-COORDINATOR-ACCEPTANCE.md) for the
local repair-loop validation steps and current Flutter client TODO.

## Run Locally

Create local Sentry configuration:

```bash
cp .env.example .env
```

Fill in the DSN for the Flutter App and a read-only `event:read` API token for
the Gateway. The token is used only by the Gateway and is not passed to the
Flutter process.

Start the API container:

```bash
./scripts/start_local.sh
```

Start the macOS App in another terminal:

```bash
./scripts/run_flutter.sh
```

Start the local Repair Coordinator in another terminal. It polls the Gateway,
runs one repair task at a time in an isolated worktree, strictly replays the
reviewed mixed UI workload, relaunches repaired Flutter code from that
worktree, and creates a pull request after validation passes:

```bash
./scripts/run_repair_coordinator.sh
```

Stop the backend without deleting persisted SQLite data:

```bash
./scripts/stop_local.sh
```

Query bounded backend and Flutter client diagnostic evidence through the local
Gateway:

```bash
./scripts/diagnostics issues --since 15m
./scripts/diagnostics show backend:<uuid>
./scripts/diagnostics show client:<sentry-group-id>
```

## Test

```bash
cd services/todo_api
uv run --group dev pytest

cd ../observability_gateway
uv run --group dev pytest

cd ../repair_coordinator
uv run --group dev pytest

cd ../../app
flutter analyze
flutter test
flutter build macos --debug
```
