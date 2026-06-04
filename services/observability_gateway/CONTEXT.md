# Observability Gateway

Read-only FastAPI service that gives Codex one diagnostics entry point across Sentry client events and Victoria backend telemetry.

## Language

**Diagnostic Case**:
A failure record prepared for repair diagnosis from one or more correlated diagnostic sources.
_Avoid_: Issue, alert, repair task

## Key Files

- `observability_gateway/main.py` - FastAPI routes, response models, adapter dispatch.
- `observability_gateway/victoria.py` - backend diagnostics from VictoriaLogs, VictoriaTraces, VictoriaMetrics.
- `observability_gateway/sentry.py` - Flutter client diagnostics from Sentry.
- `tests/` - route, adapter, and `scripts/diagnostics` CLI coverage.

## API

- `GET /diagnostics/issues?since=15m&limit=20&run_id=<optional>`
- `GET /diagnostics/issues/{issue_id}`

Issue IDs are namespaced: `backend:<uuid>` uses Victoria; `client:<group-id>` uses Sentry.

## Constraints

- Read-only and stateless. No alerting, scheduling, repair state, product mutation, or fix decisions here.
- Keep evidence bounded: backend logs are capped, client breadcrumbs are capped, metric windows are fixed.
- Do not expose arbitrary LogsQL or PromQL through the API; adapters build fixed query templates.
- Do not collect Todo titles, request bodies, credentials, tokens, cookies, or passwords.

## Configuration

- Sentry: `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, `SENTRY_PROJECT`
- Victoria: `VICTORIA_LOGS_URL`, `VICTORIA_TRACES_URL`, `VICTORIA_METRICS_URL`
- Shared: `DIAGNOSTICS_ENVIRONMENT`, default `local`
