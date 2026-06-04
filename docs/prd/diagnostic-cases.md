## Problem Statement

The repair loop currently treats backend and Flutter client failures as separate
source issues. Backend diagnostics return Victoria evidence for
`backend:<uuid>`, while client diagnostics return Sentry evidence for
`client:<group-id>`. When a user-visible failure crosses both sides, Codex may
receive only one side of the evidence or may receive a Sentry event that drifted
to the latest event in the group instead of the event that triggered repair.

This weakens repair diagnosis. Codex needs a bounded Diagnostic Case that can
represent backend-only, client-only, or correlated backend-plus-client evidence
from the same failure path.

## Solution

Introduce Diagnostic Cases in the Observability Gateway. The Gateway will expose
case-level list and detail endpoints. A case summary is lightweight and suitable
for repair polling. A case detail returns the complete bounded evidence needed
for Codex.

The Gateway will correlate backend and client evidence only when the client
Sentry event carries a backend request ID that matches a backend issue
`request_id`. Flutter will create a Sentry event for Todo API 5xx responses,
tagged with the backend request ID and workload run ID, and fingerprinted by API
failure shape. The Repair Coordinator will poll cases and write case detail to
the repair worktree evidence snapshot.

## User Stories

1. As a developer, I want a repair task to receive backend logs and client breadcrumbs when both describe the same failure, so that Codex has enough context to diagnose the user-visible problem.
2. As a developer, I want backend-only failures to remain repairable, so that missing client evidence does not block backend repairs.
3. As a developer, I want client-only failures to remain repairable, so that pure Flutter failures do not require backend telemetry.
4. As a developer, I want correlated backend/client failures represented as one Diagnostic Case, so that Codex sees one failure path instead of two disconnected issues.
5. As a developer, I want Sentry evidence locked to a concrete event ID, so that later events in the same Sentry group do not change the evidence snapshot.
6. As a developer, I want Todo API 5xx responses to create Sentry events with the backend request ID, so that Gateway correlation can use a stable request-level key.
7. As a developer, I want Todo API 4xx responses excluded from automatic Sentry repair events, so that expected client or user-input outcomes do not trigger repairs.
8. As a developer, I want API failure Sentry events fingerprinted by method, route template, and status code, so that similar failures group together without using concrete Todo IDs.
9. As a developer, I want route templates in client event metadata, so that diagnostic grouping avoids collecting unnecessary Todo-specific values.
10. As a developer, I want the Gateway case list to stay lightweight, so that polling remains cheap.
11. As a developer, I want the Gateway case detail to include full combined evidence, so that the Coordinator does not need to stitch backend and client details together.
12. As a developer, I want the Coordinator to consume Diagnostic Cases, so that repair task creation follows the same diagnostic unit Codex will inspect.
13. As a developer, I want existing source issue endpoints preserved, so that current diagnostics CLI and tests can continue to work during the transition.
14. As a developer, I want known prototype limitations documented, so that duplicate backend-only repair tasks are not mistaken for intended behavior.
15. As a developer, I want the Gateway to remain read-only and stateless, so that correlation does not turn it into a repair scheduler or task store.

## Implementation Decisions

- Add Diagnostic Case endpoints to the Observability Gateway:
  - `GET /diagnostics/cases?since=15m&limit=20&run_id=<optional>` returns lightweight summaries.
  - `GET /diagnostics/cases/{case_id}` returns complete bounded evidence.
- Keep existing source-level issue endpoints for compatibility.
- Diagnostic Case kinds are `backend-only`, `client-only`, and `correlated`.
- A correlated case is created only when a Sentry client event has a `backend_request_id` matching a backend issue `request_id`.
- A correlated case that includes backend evidence uses the backend issue ID as `case_id`.
- A client-only case binds a Sentry `event_id` during discovery and uses exact event evidence later.
- The Gateway will not rely on the Sentry group latest-event endpoint for task evidence. It will bind a concrete event during discovery and retrieve that specific event for detail.
- Flutter will actively capture a Sentry event for Todo API 5xx responses.
- Flutter will not actively capture Sentry repair events for Todo API 4xx responses.
- API failure Sentry events include tags or context for backend request ID, workload run ID, method, route template, and status code.
- API failure Sentry events use a fingerprint based on `todo-api-failure`, method, route template, and status code.
- Route templates are used instead of concrete paths in fingerprints and diagnostic metadata.
- The Repair Coordinator will poll case summaries and write case details to `.repair/evidence.json`.
- The demo Coordinator consumes cases as returned by the Gateway and does not implement complex late task upgrades when related evidence arrives after a task has already been queued.
- Backend issue IDs remain event-level in this PRD. Backend root-cause grouping is a known defect and is out of scope.

## Testing Decisions

- Tests should validate externally visible behavior: Gateway response shapes, Sentry API calls, Todo API client event metadata, and Coordinator polling/evidence behavior.
- Observability Gateway tests should cover:
  - listing backend-only, client-only, and correlated case summaries;
  - returning full backend evidence for backend-only case detail;
  - returning exact Sentry event evidence for client-only case detail;
  - returning combined backend and client evidence for correlated case detail;
  - binding a concrete Sentry event ID during discovery instead of using group latest evidence during detail lookup.
- Sentry adapter tests should use mock HTTP transports, following existing Sentry diagnostics tests.
- Victoria adapter tests should reuse existing backend diagnostics patterns and fixed LogsQL assertions.
- Flutter tests should cover Todo API 5xx active Sentry capture metadata and fingerprint behavior without depending on real Sentry SaaS.
- Flutter tests should confirm 4xx responses do not create active repair Sentry events.
- Repair Coordinator tests should cover polling cases and writing case detail snapshots, following existing process and poll tests.
- Tests should not assert private implementation details such as helper method names or internal query construction beyond the public fixed-query contract already tested in the Gateway adapters.

## Out of Scope

- Production-grade issue indexing, caching, RBAC, audit storage, or webhook scheduling.
- Backend root-cause grouping by stacktrace or exception signature.
- Late-arriving case upgrade logic in the Coordinator.
- Manual UI breadcrumbs for every Todo interaction.
- Correlation by time proximity, user ID, session ID, or run ID alone.
- Collecting Todo titles, request bodies, credentials, tokens, cookies, or passwords.
- Replacing the existing source-level issue endpoints immediately.

## Further Notes

This PRD follows ADR 0003, `diagnostic-cases-v0.1`. The demo accepts that
late-arriving correlations may remain separate repair tasks. That trade-off
keeps the prototype focused on proving case-level evidence flow without adding
production task reconciliation.
