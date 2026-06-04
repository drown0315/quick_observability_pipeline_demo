## Parent

Related to #24.

## What to build

Add the first Diagnostic Case path through the Gateway. The Gateway should list
backend-only Diagnostic Case summaries and return full backend evidence for a
selected backend-only case. Existing source issue endpoints should continue to
work during this transition.

## Acceptance criteria

- [ ] `GET /diagnostics/cases` returns lightweight backend-only case summaries.
- [ ] A backend-only case uses the backend issue ID as `case_id`.
- [ ] `GET /diagnostics/cases/{case_id}` returns the same bounded backend evidence currently available from source issue detail.
- [ ] Existing `/diagnostics/issues` list and detail behavior remains compatible.
- [ ] Gateway route tests cover backend-only case list and detail behavior.

## Blocked by

None - can start immediately.
