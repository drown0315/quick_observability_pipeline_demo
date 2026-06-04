---
status: proposed
doc_version: diagnostic-cases-v0.1
---

# Introduce Diagnostic Cases for correlated repair evidence

The Gateway should expose Diagnostic Cases as the repair-loop diagnostic unit
instead of only listing source issues. A Diagnostic Case may contain a backend
issue, a Sentry client event, or both when the Gateway can correlate them with
read-only evidence such as a backend request ID. The Gateway remains stateless
and does not create repair tasks; the Repair Coordinator materializes tasks from
cases and preserves deduplication state in SQLite.

## Consequences

- Gateway issue endpoints can remain as source-level compatibility APIs, but
  repair polling should move toward case-level diagnostics.
- Sentry client cases must bind a concrete event ID during discovery so later
  evidence queries do not drift to a different event in the same Sentry group.
- Correlated cases that include a backend issue use the backend issue ID as the
  stable case identity; request IDs are correlation evidence, not primary case
  identity.
- The demo Coordinator consumes cases as returned by the Gateway and does not
  upgrade already-queued tasks when related client or backend evidence arrives
  later. Late-arriving correlations may therefore remain separate repair tasks
  in this prototype.
