## Parent

Related to #24.

## What to build

Capture Todo API 5xx responses as Sentry client events so backend failures can
carry useful client-side breadcrumbs and request correlation data. These events
should be grouped by API failure shape, not by concrete Todo IDs.

## Acceptance criteria

- [ ] Flutter actively captures a Sentry event for Todo API 5xx responses.
- [ ] Flutter does not actively capture a repair Sentry event for Todo API 4xx responses.
- [ ] Captured 5xx events include backend request ID, workload run ID, method, route template, and status code as tags or context.
- [ ] Captured 5xx events use a fingerprint based on `todo-api-failure`, method, route template, and status code.
- [ ] Tests verify 5xx capture metadata and 4xx non-capture behavior without calling real Sentry SaaS.

## Blocked by

None - can start immediately.
