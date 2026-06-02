# Quick Observability Pipeline Prototype

## Goal

Validate a feedback loop in which Codex observes failures from a running Flutter macOS Todo application and its FastAPI backend, queries bounded diagnostic evidence through one local entry point, modifies product code, restarts only the affected components, and re-runs the same user journey to confirm the fix.

The prototype simulates defects that escaped pre-release testing. The injected defects are deterministic so the loop can be demonstrated repeatedly, but they are not encoded as expected failures in the test suite or workload assertions.

## Non-goals

- Production deployment, alert routing, or webhook-driven Codex wake-up.
- Automated pull request merges or production releases.
- Production-grade issue indexing, deduplication, caching, RBAC, or audit storage.
- Android, iOS, ANR, or real-device performance validation.
- Grafana, Jaeger UI, or additional observability dashboards.
- Full client log upload or sensitive Todo content collection.

## Topology

```text
Flutter macOS App
  -> sentry_flutter
  -> Sentry SaaS

Flutter macOS App
  -> HTTP API
  -> FastAPI + SQLite
  -> JSON stdout logs
  -> OTLP traces and metrics
  -> OpenTelemetry Collector
  -> VictoriaLogs / VictoriaTraces / VictoriaMetrics

Codex
  -> scripts/diagnostics
  -> Observability Gateway
  -> Sentry API and Victoria APIs

Repair Coordinator
  -> Observability Gateway
  -> Codex
  -> flutter-mcp-toolkit
  -> GitHub pull request
```

The Gateway is a read-only, stateless aggregation layer. It bounds and normalizes diagnostic evidence but does not alert, schedule tasks, or decide fixes.

The Repair Coordinator is a local orchestration service. It polls the Gateway
for new issues, stores repair-task state in SQLite, invokes Codex for one task
at a time, replays reviewed UI workloads, and creates a pull request after a
successful repair. The Coordinator does not bypass the Gateway to query Sentry
or Victoria services directly.

## Repository Layout

```text
app/                              Flutter macOS App
services/
  todo_api/                       FastAPI + SQLite + OTel
  observability_gateway/          Read-only aggregation Gateway
  repair_coordinator/             Local polling and repair-task orchestration
observability/
  otel-collector-config.yaml
harness/
  normal_todo_journey.hs.yaml
  mixed_user_workload.hs.yaml
scripts/
  start_local.sh
  stop_local.sh
  run_repair_coordinator.sh
  diagnostics
docker-compose.yml
.env.example
```

## Todo API

The backend exposes:

```text
GET    /todos
POST   /todos
PATCH  /todos/{id}
DELETE /todos/{id}
```

A Todo has:

```json
{
  "id": 42,
  "title": "buy milk",
  "completed": false
}
```

SQLite persists to a Docker volume. The workload creates its own Todo records and does not rely on pre-existing data.

## Observability Data

### Flutter Client

The Flutter macOS App sends client exceptions and automatic context to one Sentry SaaS project named `todo-flutter-macos`.

Collect:

- Uncaught exceptions and stacktraces.
- Release and environment.
- Automatic page-navigation and HTTP breadcrumbs where supported.
- Fixed demo user ID and per-launch session ID.

Do not collect:

- Full client debug logs.
- Todo titles.
- HTTP bodies.
- Credentials or authorization tokens.

### FastAPI Backend

FastAPI does not send events to Sentry. It emits:

- Structured JSON logs at `INFO` and above.
- OTLP traces for HTTP requests, handlers, and SQLite operations.
- OTLP metrics for request count, error rate, and latency.

Logs are collected from container stdout by OpenTelemetry Collector and sent to VictoriaLogs. Traces and metrics are sent to Collector over OTLP, then fanned out to VictoriaTraces and VictoriaMetrics.

Each HTTP completion log includes:

```json
{
  "event_type": "http_request_completed",
  "service": "todo-api",
  "method": "DELETE",
  "path_template": "/todos/{id}",
  "status_code": 500,
  "duration_ms": 18,
  "trace_id": "...",
  "request_id": "...",
  "user_id": "demo-user",
  "release": "...",
  "environment": "local",
  "run_id": "..."
}
```

Unhandled exceptions emit:

```json
{
  "event_type": "unhandled_exception",
  "issue_id": "backend:<uuid>",
  "service": "todo-api",
  "exception_type": "RuntimeError",
  "message": "todo deletion failed",
  "trace_id": "...",
  "request_id": "...",
  "status_code": 500,
  "user_id": "demo-user",
  "release": "...",
  "environment": "local",
  "run_id": "..."
}
```

Exception details retain stacktraces. Logs must not retain Todo titles, authorization tokens, cookies, passwords, or complete HTTP bodies. Paths use templates rather than raw parameter values.

## Correlation

The prototype records:

| Field | Purpose |
| --- | --- |
| `user_id` | Identify the fixed demo user. |
| `session_id` | Group one Flutter App launch. |
| `trace_id` | Correlate a distributed call chain where SDK propagation supports it. |
| `request_id` | Identify one backend HTTP request for manual searching. |
| `release` | Separate events produced by different code versions. |
| `environment` | Restrict prototype queries to `local`. |
| `run_id` | Separate local harness runs before and after repair. |

Cross-platform trace propagation uses SDK defaults first. If validation proves Flutter Sentry and FastAPI OpenTelemetry propagation incompatible, add a network-boundary adapter rather than business-level instrumentation.

`run_id` is a local harness field, not a production tracing concept. The workload runner creates a UUID for each run and sets it in the already-running debug Flutter App through a dedicated MCP tool. The Flutter HTTP client forwards it as `x-workload-run-id`, and FastAPI records it in structured logs.

### Trace Propagation Validation

The Flutter App uses `SentryHttpClient` at the Todo API network boundary and
enables Sentry sampling plus W3C `traceparent` propagation. This is the
adapter needed for compatibility with FastAPI OpenTelemetry extraction:
Sentry's default `sentry-trace` header alone is useful for Sentry context, but
the backend OpenTelemetry SDK expects `traceparent` for distributed trace
correlation and only exports backend spans for sampled traces.

The adapter is intentionally limited to the HTTP client boundary. Todo CRUD
operations remain free of business-level trace instrumentation.

Diagnostics detail responses expose the trace ID from both sides when present:

- Flutter client details return `trace_correlation.trace_id` from the Sentry
  event trace context.
- Backend details return `trace_correlation.trace_id` from the current
  OpenTelemetry span recorded in backend logs.

## Gateway API

The Gateway exposes:

```http
GET /diagnostics/issues?since=15m&limit=20&run_id=<optional>
GET /diagnostics/issues/{issue_id}
```

The list endpoint returns lightweight issue summaries. The detail endpoint returns a summary plus bounded raw evidence:

- Complete exception stacktrace.
- Up to 100 relevant logs.
- All spans from the matching trace.
- Metrics aggregated by one-minute buckets for the five minutes before and after the issue.

Gateway adapters use:

- Sentry API for Flutter issues and events.
- Fixed LogsQL templates for VictoriaLogs.
- Jaeger Query API for VictoriaTraces.
- Fixed PromQL templates for VictoriaMetrics.

Codex does not submit arbitrary LogsQL or PromQL through the Gateway.

The CLI maps to the Gateway:

```bash
./scripts/diagnostics issues --since 15m
./scripts/diagnostics show backend:<uuid>
./scripts/diagnostics issues --since 15m --format text
```

JSON is the default output format.

## Workload

The primary workload drives the real Flutter UI through `mcp_toolkit`, not direct Todo API calls.

First, Codex uses generic toolkit operations to confirm stable semantic nodes:

```text
fmt_semantic_snapshot
fmt_enter_text
fmt_tap_widget
fmt_wait_for
fmt_hot_reload_and_capture
fmt_get_app_errors
```

The stable journey is then encoded as a `flutter_harness` `*.hs.yaml` file. The mixed workload performs:

```text
1. Create a normal Todo.
2. Complete a normal Todo.
3. Create another normal Todo.
4. Delete a normal Todo.
5. Create a Todo whose title contains crash.
6. Delete that Todo.
7. Create a Todo whose title contains mobile-crash.
8. Complete that Todo.
```

The workload describes user actions only. It does not assert that a crash or HTTP `500` is expected. On an App crash, UI failure, or timeout, it stops and returns the completed steps, failed step, failure time, last semantic snapshot, and App errors.

The debug Flutter App registers one app-specific MCP tool:

```text
todo_set_workload_run_id(run_id)
```

This tool only stores a validated workload UUID in memory so the HTTP client can forward it. It does not bypass UI behavior or expose application data.

## Injected Defects

The backend contains a defect in the real deletion path: deleting a Todo whose title contains `crash` raises an unhandled exception.

The Flutter client contains a defect in the real completion path: completing a Todo whose title contains `mobile-crash` raises an uncaught exception.

These are hidden product defects for workload purposes. They are not represented as expected failures in tests.

## Repair Loop

The Repair Coordinator starts Codex after polling the Gateway and finding a new
issue. The first version uses polling rather than webhook delivery. Each issue
ID creates at most one repair task unless an operator explicitly retries a
failed task.

```text
for up to 3 attempts:
  invoke Codex in the task worktree
  query bounded diagnostics through the CLI
  run the reviewed workload with a new run_id
  if the journey succeeds and the run created no new issues:
    commit, push, and create a pull request
    stop successfully
  analyze the evidence
  modify allowed product code
  restart only affected components
stop and report evidence, attempt history, and current diff
```

Codex may use additional Flutter MCP operations while diagnosing a failure.
Formal replay uses a reviewed `*.hs.yaml` workload interpreted strictly by the
Coordinator. Selector resolution requires exactly one semantic match; missing
or ambiguous selectors fail validation instead of falling back to coordinates
or an index.

Each repair task runs serially in its own Git worktree on a
`codex/repair-<task-id>` branch. A successful task creates a normal pull request
but does not merge it. The local-first prototype reuses the developer machine's
Git and `gh` authentication; a later version should use an isolated bot token.

Allowed automatic repair paths:

```text
app/lib/
services/todo_api/
```

Protected validation and observability paths:

```text
harness/
services/observability_gateway/
observability/
docker-compose.yml
scripts/diagnostics
```

Restart behavior:

```text
services/todo_api/ changed
  -> docker compose up -d --build todo-api

app/lib/ changed
  -> relaunch Flutter App from the task worktree
  -> flutter-mcp-toolkit hot restart
```

## Configuration

Local `.env` configuration includes:

```env
SENTRY_DSN=...
SENTRY_AUTH_TOKEN=...
SENTRY_ORG=...
SENTRY_PROJECT=todo-flutter-macos
APP_RELEASE=dev-20260530-001
APP_ENVIRONMENT=local
```

`SENTRY_AUTH_TOKEN` is read-only and used only by Gateway. Secrets do not enter the repository.

`scripts/start_local.sh` checks required configuration, builds and starts Docker Compose services, waits for health checks, and prints the Flutter startup command:

```bash
flutter run -d macos
```

`scripts/stop_local.sh` stops local containers while retaining the SQLite volume.

## Acceptance Criteria

### Backend Failure Loop

1. The UI workload creates a Todo whose title contains `crash`.
2. Deleting the Todo reaches FastAPI and returns an unexpected `500`.
3. Collector sends the backend logs and trace to Victoria services.
4. Codex obtains the exception stacktrace, relevant logs, and spans through `scripts/diagnostics`.
5. Codex modifies the FastAPI product code and rebuilds only `todo-api`.
6. Re-running the same UI workload with a new `run_id` completes the deletion without creating a new backend issue.

### Client Failure Loop

1. The UI workload creates a Todo whose title contains `mobile-crash`.
2. Completing the Todo raises an unexpected Flutter exception.
3. Sentry receives the client exception, stacktrace, and breadcrumbs.
4. Codex obtains bounded Sentry evidence through `scripts/diagnostics`.
5. Codex modifies Flutter product code and hot restarts the App.
6. Re-running the same UI workload with a new `run_id` completes without a new client issue.

## Implementation Order

1. Build FastAPI + SQLite CRUD, Flutter macOS Todo UI, and Docker Compose.
2. Add backend JSON logs, OpenTelemetry instrumentation, Collector, and Victoria services.
3. Add the stateless Gateway and diagnostics CLI.
4. Add `sentry_flutter`, release/environment fields, and validate SDK trace propagation.
5. Add `mcp_toolkit`, the debug-only `run_id` MCP tool, `flutter_harness` journeys, injected defects, and the bounded repair loop.
