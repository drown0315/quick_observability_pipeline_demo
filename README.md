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
[ADR 0001](docs/adr/0001-hybrid-observability-pipeline.md).

## Run Locally

Start the API container:

```bash
./scripts/start_local.sh
```

Start the macOS App in another terminal:

```bash
cd app
flutter run -d macos
```

Stop the backend without deleting persisted SQLite data:

```bash
./scripts/stop_local.sh
```

Query bounded backend diagnostic evidence through the local Gateway:

```bash
./scripts/diagnostics issues --since 15m
./scripts/diagnostics show backend:<uuid>
```

## Test

```bash
cd services/todo_api
uv run --group dev pytest

cd ../observability_gateway
uv run --group dev pytest

cd ../../app
flutter analyze
flutter test
flutter build macos --debug
```
