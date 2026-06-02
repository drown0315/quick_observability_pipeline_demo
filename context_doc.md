# CONTEXT.md: A Convention for LLM-Friendly Repository Documentation

> **TL;DR**: Place `CONTEXT.md` files throughout your repository tree to give LLMs the context they need. Each file describes its directory and links to child CONTEXT files. LLMs walk up the tree from any file to gather layered context—general to specific. Scales to large codebases, stays human-maintainable, works with any LLM tool.

## Problem Statement

Large Language Models working with codebases face a fundamental tension:

1. **Too little context** - Without understanding architecture, conventions, and relationships, LLMs make mistakes that any team member would avoid
2. **Too much context** - Loading entire documentation sets into every conversation is expensive, slow, and wastes context window on irrelevant information

Existing approaches fall short:

- **Single root file** (`.cursorrules`, `CLAUDE.md`, etc.) - Doesn't scale; becomes either too large or too superficial for complex projects
- **Traditional docs** - Written for humans; too verbose, wrong granularity for LLM consumption
- **Code comments** - Scattered, inconsistent, focused on implementation not architecture

## The CONTEXT.md Convention

### Core Idea

Place `CONTEXT.md` files throughout your repository tree. Each file provides focused context for its directory and links to child CONTEXT files. An LLM working on any file can walk up the directory tree, reading CONTEXT.md files, to gather exactly the context needed.

### Structure

```
repo/
├── CONTEXT.md              # Project overview, architecture, key conventions
├── src/
│   ├── CONTEXT.md          # Source organization, patterns used
│   ├── api/
│   │   └── CONTEXT.md      # API design, endpoints, authentication
│   └── database/
│       └── CONTEXT.md      # Schema, migrations, query patterns
├── test/
│   └── CONTEXT.md          # Testing philosophy, infrastructure, how to run
└── scripts/
    └── CONTEXT.md          # Build, deploy, maintenance scripts
```

### Key Principles

#### 1. Locality
Context lives next to the code it describes. The CONTEXT.md in `src/api/` describes the API code, not the whole project.

#### 2. Hierarchical
Parent CONTEXT files link to children. Reading from root down gives progressively more detail. Reading from a leaf up gives progressively more context.

#### 3. LLM-Optimized
Written for LLM consumption:
- Concise, factual, structured
- Focus on "what you need to know to work here"
- Include concrete examples (file paths, command lines, code patterns)
- Avoid verbose explanations that humans need but LLMs don't

#### 4. Human-Reviewable
Each file is small enough that a developer can review changes without needing to understand the entire repository. This enables distributed maintenance.

#### 5. Navigable
Each CONTEXT.md should link to:
- Child CONTEXT.md files it knows about
- Related CONTEXT.md files in other parts of the tree
- Key source files it references

### Content Guidelines

A CONTEXT.md should include (as relevant):

**Always:**
- Purpose of this directory/subsystem
- Key files and what they do
- Links to child CONTEXT.md files

**Often:**
- Architecture decisions and patterns used
- Important conventions specific to this area
- Common tasks and how to do them
- Gotchas and things to watch out for

**Sometimes:**
- Historical context ("this exists because...")
- Relationship to other parts of the system
- Testing approach for this area

**Never:**
- API documentation (use standard tools)
- Tutorials or onboarding docs (those are for humans)
- Content that duplicates information in child CONTEXT files

### Example Root CONTEXT.md

```markdown
# Project Name

Brief description of what this project does.

## Architecture Overview

[High-level architecture: major components, data flow, key technologies]

## Repository Structure

- `src/` - Source code ([src/CONTEXT.md](src/CONTEXT.md))
- `test/` - Test suite ([test/CONTEXT.md](test/CONTEXT.md))
- `scripts/` - Build and maintenance scripts

## Key Conventions

- [Convention 1]
- [Convention 2]

## Common Commands

```bash
npm install     # Install dependencies
npm run build   # Build the project
npm test        # Run tests
```

## Working with This Codebase

[Key things an LLM needs to know to be effective here]
```

### Example Subsystem CONTEXT.md

```markdown
# Authentication Subsystem

Handles user authentication and session management.

## Components

- `auth.ts` - Main authentication logic
- `session.ts` - Session management
- `providers/` - OAuth provider implementations

## How Authentication Works

1. User submits credentials
2. [Step 2]
3. [Step 3]

## Key Patterns

- All auth functions return `AuthResult` type
- Sessions are stored in Redis (see `../database/CONTEXT.md`)

## Testing

Auth tests require a test database. See [../test/CONTEXT.md](../test/CONTEXT.md).
```

### Verification Task

The root CONTEXT.md should include a section that enables LLMs to verify the CONTEXT tree. This enables periodic maintenance - you can ask an LLM to read a repository and all its context files and point out files that need updating.

**To verify a CONTEXT tree, an LLM should check:**

1. **Reference Integrity**
   - All linked CONTEXT.md files exist
   - All child CONTEXT.md files are linked from their parent
   - No orphaned CONTEXT.md files

2. **Code Reference Validation**
   - File paths mentioned in each CONTEXT.md actually exist
   - Directory structures described match reality
   - Command examples are still valid

3. **Content Accuracy**
   - Descriptions match current implementation
   - Architectural claims are still true
   - No stale information about removed features

**Example maintenance section for your root CONTEXT.md:**

```markdown
## Maintaining the CONTEXT Tree

This repository uses the [CONTEXT.md convention](https://github.com/the-michael-toy/llm-context-md).

**Verification command:** "Read the CONTEXT tree and verify it is up to date"
```

## Usage Patterns

### For LLMs

When starting work on a file at `src/foo/bar/baz.ts`:

1. Read `CONTEXT.md` (root)
2. Read `src/CONTEXT.md`
3. Read `src/foo/CONTEXT.md` (if exists)
4. Read `src/foo/bar/CONTEXT.md` (if exists)

This provides layered context from general to specific.

### For Humans

When reviewing a CONTEXT.md change:
- You only need to understand that subsystem
- Check that referenced files/paths exist
- Verify technical accuracy for that area

When adding a new subsystem:
- Create CONTEXT.md describing it
- Link from parent CONTEXT.md
- Include links to any child CONTEXT.md files

## Comparison to Alternatives

| Approach | Scales? | Incremental? | Human-Maintainable? | Tool-Agnostic? |
|----------|---------|--------------|---------------------|----------------|
| Single root file | No | No | Barely | Yes |
| Tool-specific (`.cursorrules`) | No | No | Barely | No |
| Full docs in context | No | No | Yes | Yes |
| **CONTEXT.md tree** | **Yes** | **Yes** | **Yes** | **Yes** |

### Related Standards

- **[llms.txt](https://llmstxt.org/)** - Focused on websites providing LLM-friendly content; single file, web-oriented
- **AGENTS.md** - Similar goal for repositories, but typically single file at root
- **[Model Context Protocol](https://modelcontextprotocol.io/)** - Protocol for tool integration, different scope

CONTEXT.md complements these by solving the hierarchical codebase problem they don't address.

## Adoption

### Minimal Adoption
Just add a root `CONTEXT.md` with project overview. This alone is valuable.

### Incremental Adoption
Add CONTEXT.md files to subsystems as you work on them. No need to do everything at once.

### Full Adoption
Complete tree with verification tasks and regular maintenance schedule.

## File Naming

The convention uses `CONTEXT.md` specifically:
- ALL CAPS signals "this is metadata, not content"
- `.md` allows formatting and links
- Single consistent name makes discovery trivial

Alternatives considered:
- `AI.md`, `LLM.md` - Too tool-specific
- `README.md` - Already has established meaning
- `.context` - Hidden files are less discoverable

## Real-World Examples

See the [`examples/`](examples/) directory for projects using this convention:

- **[Malloy](examples/malloy.md)** - A semantic data modeling and query language. Complex monorepo with multiple packages, demonstrates full CONTEXT.md tree adoption.

## Adopters

Projects using the CONTEXT.md convention:

- [Malloy](https://github.com/malloydata/malloy) - Semantic data modeling language

*Using CONTEXT.md in your project? Submit a PR to add yourself!*

## Contributing

This is an evolving convention. Contributions welcome:

- **Adopt it** - Try it in your project and share what works
- **Report issues** - What's unclear? What doesn't work?
- **Suggest improvements** - Open an issue or PR
- **Add examples** - Share your CONTEXT.md files as real-world examples

## License

This specification is released under [CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/) - no rights reserved. Use it however you want.

---

The key insight is that **context should be structured like code** - modular, hierarchical, and local to what it describes.
