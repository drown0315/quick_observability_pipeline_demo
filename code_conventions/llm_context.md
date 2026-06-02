# LLM Context Writing Conventions

Write `CONTEXT.md` files as compact code maps and guardrails for LLM agents.
The goal is to reduce random code exploration, not to document the whole system.

## Purpose

A good `CONTEXT.md` should help an LLM:

- know which files to read first
- avoid irrelevant files and generated artifacts
- respect subsystem boundaries
- preserve domain language and safety constraints

It should not let the LLM skip reading code entirely.

## Progressive Disclosure

- Parent context files should navigate, not explain child subsystems.
- Child context files should contain only what is necessary to work in that directory.
- Link downward to more specific context instead of copying detail upward.
- Keep each file small enough to load without crowding the task context.

## What To Include

- Directory or subsystem responsibility.
- Key source files and why they matter.
- Architectural boundaries the LLM must not cross.
- Domain vocabulary that must be preserved.
- Non-obvious runtime or validation requirements.

## What To Omit

- Generic commands an LLM can infer, such as ordinary pytest or npm commands.
- API documentation that belongs in code or generated docs.
- Implementation walkthroughs already visible in source files.
- README, ADR, or child context content copied verbatim.
- Generated folders, caches, virtual environments, and build outputs.

## Writing Rule

Prefer: "what this area is, where to look, what not to violate."

Avoid: "how every part of the implementation works."
