# Services

Backend and local orchestration services for the Todo observability repair loop.

## Map

- `todo_api/` owns Todo CRUD behavior and backend telemetry. See [todo_api/CONTEXT.md](todo_api/CONTEXT.md).
- `observability_gateway/` exposes bounded diagnostics for Codex. See [observability_gateway/CONTEXT.md](observability_gateway/CONTEXT.md).
- `repair_coordinator/` polls the Gateway, invokes Codex, replays workloads, and prepares PRs. See [repair_coordinator/CONTEXT.md](repair_coordinator/CONTEXT.md).

## Boundary

Diagnostics flow through the Gateway. Product Todo behavior stays in `todo_api/`.
