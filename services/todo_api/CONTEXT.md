# Todo API

FastAPI service that owns SQLite-backed Todo CRUD behavior and emits bounded
backend telemetry for the local observability repair loop.

## Key Files

- `todo_api/main.py` - FastAPI app, Todo routes, request middleware, exception logging.
- `todo_api/todo_persistence.py` - SQLite CRUD rules and `Todo` response model.
- `todo_api/database.py` - database path, connection setup, schema initialization, SQLite tracing.
- `todo_api/observability.py` - JSON request logger, OTLP exporters, metrics, traces, release/environment metadata.
- `tests/test_todos.py` - API behavior, persistence across app restart, and diagnostic logging safeguards.
- `tests/test_todo_persistence.py` - persistence-layer CRUD and missing-Todo behavior.
- `Dockerfile` - local container runtime and default `/data/todos.db` path.

## API Surface

- `GET /health`
- `GET /todos`
- `POST /todos`
- `PATCH /todos/{todo_id}`
- `DELETE /todos/{todo_id}`

Use `Todo` for the domain object. A Todo has `id`, `title`, and `completed`.
Missing Todos return `404` through `TodoNotFoundError`.

## Constraints

- Preserve SQLite-backed Todo CRUD behavior unless the requested change
  explicitly modifies it.
- Keep Todo ordering stable by ascending `id`.
- Do not log Todo titles, request bodies, authorization headers, cookies,
  credentials, or tokens in diagnostic events.
- Keep diagnostic issue IDs namespaced as `backend:<uuid>` for unhandled backend
  exceptions.
- Keep `/health` out of request telemetry.
- Preserve workload correlation through valid `x-workload-run-id` UUID headers;
  invalid correlation IDs are ignored.
- The deliberate delete failure for Todos whose title contains `crash` is part
  of the prototype's backend issue path. Change it only when replacing that
  demo behavior intentionally.

## Observability Boundary

This service emits bounded logs, metrics, and traces. It does not aggregate
diagnostics, schedule repairs, invoke Codex, or publish pull requests. Gateway
query logic belongs in `services/observability_gateway/`; repair workflow logic
belongs in `services/repair_coordinator/`.

## Configuration

- Database: `TODO_DB_PATH`, default `todos.db`
- Telemetry toggle: `TODO_OTEL_ENABLED`, default `false`
- Metadata: `TODO_RELEASE`, `TODO_ENVIRONMENT`
- OTLP: `OTEL_EXPORTER_OTLP_ENDPOINT` or per-signal
  `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT`,
  `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT`,
  `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
