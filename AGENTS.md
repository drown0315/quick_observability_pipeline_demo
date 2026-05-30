# Agent Guide

## Project Purpose

This repository is a local-first validation prototype for an automated Codex
repair loop. A Flutter macOS Todo App and its FastAPI backend emit diagnostic
signals. The intended workflow is to reproduce a user-visible failure, inspect
bounded evidence through the diagnostics entry point, repair product code, and
replay the same UI journey.

Read these files before changing architecture or domain behavior:

- [README.md](README.md)
- [CONTEXT.md](CONTEXT.md)
- [Prototype Scope](docs/PROTOTYPE-SCOPE.md)
- [ADR 0001](docs/adr/0001-hybrid-observability-pipeline.md)

## Repository Layout

```text
app/                    Flutter macOS Todo App
services/todo_api/      FastAPI + SQLite backend
docs/                   Prototype scope and architecture decisions
scripts/                Local backend lifecycle helpers
.agents/skills/         Project-local agent workflows
```

The prototype scope also documents planned observability components. Do not
assume a planned directory or service has already been implemented.

## Domain Language

Use `Todo` for the task-tracking domain object. Avoid alternate names such as
`task item` or `note`. Keep product behavior aligned with [CONTEXT.md](CONTEXT.md).

## Development Commands

Start and stop the backend:

```bash
./scripts/start_local.sh
./scripts/stop_local.sh
```

Run the backend tests:

```bash
cd services/todo_api
uv run --group dev pytest
```

Validate the Flutter App:

```bash
cd app
flutter analyze
flutter test
flutter build macos --debug
```

Run the App locally:

```bash
cd app
flutter run -d macos
```

## Change Guidelines

- Keep the prototype local-first and preserve the architecture recorded in the
  ADR unless a new decision explicitly replaces it.
- Treat the Observability Gateway as a read-only, stateless aggregation layer.
- Drive product validation through the real Flutter UI when exercising user
  journeys; do not replace UI behavior with direct API shortcuts.
- Keep diagnostic evidence bounded and avoid collecting Todo titles, request
  bodies, credentials, or authorization tokens.
- Preserve SQLite-backed Todo CRUD behavior unless the requested change
  intentionally modifies it.
- Add focused tests for behavioral changes and run the relevant backend or
  Flutter validation commands before submitting a change.

## Skills

Project-local workflows live in [.agents/skills](.agents/skills). Use the
relevant skill when a request matches its scope, especially the Flutter MCP
toolkit skills when inspecting or driving a running Flutter App.
