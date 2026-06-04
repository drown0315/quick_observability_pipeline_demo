## Parent

Related to #24.

## What to build

Switch the Repair Coordinator to poll Diagnostic Cases instead of source issues.
When a task is claimed, the Coordinator should request the case detail and write
that combined evidence into the repair worktree for Codex.

## Acceptance criteria

- [ ] The Coordinator polls `GET /diagnostics/cases` for repair candidates.
- [ ] The Coordinator creates repair tasks from case summaries.
- [ ] When writing `.repair/evidence.json`, the Coordinator requests `GET /diagnostics/cases/{case_id}`.
- [ ] Evidence snapshots include the case ID, case kind, source identities, and full case detail.
- [ ] Existing repair flow validation still runs through reviewed Flutter workloads.
- [ ] Tests cover polling a correlated case and writing combined evidence for Codex.
- [ ] The demo does not implement late-arriving case upgrade logic.

## Blocked by

- Correlated Diagnostic Cases from the Gateway.
