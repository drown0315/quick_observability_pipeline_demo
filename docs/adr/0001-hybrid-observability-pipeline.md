# Use a hybrid observability pipeline for the validation prototype

The first validation prototype uses `sentry_flutter` with Sentry SaaS for Flutter macOS client exceptions and automatic context, while the FastAPI backend remains vendor-neutral and emits logs, traces, and metrics through OpenTelemetry Collector to VictoriaLogs, VictoriaTraces, and VictoriaMetrics. Codex reads both data sources through a local read-only Observability Gateway and its `scripts/diagnostics` CLI so the feedback loop has one query entry point without requiring a unified storage backend prematurely.

## Consequences

- FastAPI does not send exceptions to Sentry.
- The Gateway aggregates and bounds diagnostic evidence but does not alert, schedule tasks, or decide fixes.
- The prototype Gateway is stateless. A production version would need persisted issue indexing, deduplication, and repair-task state before it could drive automated work safely at production scale.
- Codex diagnosis is started manually in the first version.
- Cross-platform trace propagation relies on SDK defaults first; a network-boundary adapter is added only if validation proves it necessary.
