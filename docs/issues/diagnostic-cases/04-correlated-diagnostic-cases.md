## Parent

Related to #24.

## What to build

Return correlated Diagnostic Cases from the Gateway when backend and client
sources are tied by the same backend request ID. A correlated case should expose
one repair diagnosis object with both backend and client source identities, and
case detail should return combined bounded evidence.

## Acceptance criteria

- [ ] Gateway correlates a client source with a backend source when `client.backend_request_id` matches `backend.request_id`.
- [ ] A correlated case that includes backend evidence uses the backend issue ID as `case_id`.
- [ ] Correlated case summaries include backend source identity, client source identity, and correlation metadata.
- [ ] Correlated case detail returns bounded backend evidence and exact Sentry event evidence together.
- [ ] Tests cover backend-only, client-only, and correlated cases in the same listing window.

## Blocked by

- Diagnostic Case backend-only API foundation.
- Exact Sentry event binding for client Diagnostic Cases.
- Todo API 5xx Sentry client event capture.
