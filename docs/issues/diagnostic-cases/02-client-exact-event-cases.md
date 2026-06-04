## Parent

Related to #24.

## What to build

Add client-only Diagnostic Cases that bind a concrete Sentry event during
discovery. A client case should keep using the Sentry group as its source issue
identity while using the bound event ID for stable evidence lookup.

## Acceptance criteria

- [ ] `GET /diagnostics/cases` returns lightweight client-only case summaries.
- [ ] Each client-only case summary includes the Sentry group issue ID and the bound event ID.
- [ ] `GET /diagnostics/cases/{case_id}` retrieves evidence from the bound Sentry event, not from the group's current latest event.
- [ ] Client case detail includes bounded Sentry stacktrace, breadcrumbs, context, and trace correlation when present.
- [ ] Tests cover a Sentry group whose latest event differs from the bound event and verify that the bound event evidence is returned.

## Blocked by

- Diagnostic Case backend-only API foundation.
