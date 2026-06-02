# Todo

A small task-tracking application used to exercise an automated observability feedback loop.

## Repository Context

- `app/` contains the Flutter macOS Todo App.
- `services/` contains backend, diagnostics, and repair-loop services. See [services/CONTEXT.md](services/CONTEXT.md).
- `docs/` contains prototype scope and architecture decisions.

## Language

**Todo**:
A task recorded by a user for later completion.
_Avoid_: Task item, note

## Maintaining the CONTEXT Tree

This repository uses layered `CONTEXT.md` files for LLM-oriented project understanding.

Keep each file small. Link to child context files instead of copying subsystem detail upward.
