---
name: write-pr-description
description: Use when creating pull requests to write clear, structured PR descriptions that help reviewers understand changes.
metadata:
  mcpmarket-version: 1.0.0
---
# Write PR Description

Create structured pull request descriptions that provide context for reviewers.

## Workflow

When user asks to create or update a PR description:

1. Review all commits in the branch.
2. Read the branch diff to understand the full scope.
3. Identify the runtime behavior changed by the PR, not only files changed.
4. Draft the PR body using `templates/pr-description.md`.
5. If creating or editing the PR, use `gh pr create`, `gh pr edit`, or the GitHub REST API.

## Required Sections

### Summary
- Explain the PR in one or two sentences.
- State what changed and why it matters.

### What Changed
- List specific changes grouped by area.
- Focus on externally reviewable behavior and public contracts.
- Include notable tests or docs added with the behavior.

### Why
- Explain the bug, product need, or technical motivation.
- Name the tradeoff or boundary chosen.
- Avoid vague claims such as "improves reliability" without explaining the mechanism.

### Automated Validation
- List commands actually run.
- Keep command output summaries short.
- Do not mix automated checks with manual product acceptance.

### Manual Acceptance
- Include concrete steps only when reviewers need runtime or product validation.
- Separate successful workflow validation from error/issue validation.
- State the expected observation for each command.
- If a command only lists failures or issues, say that explicitly.
- Do not imply a successful request will appear in an issue list.

### Related Issues
- Use `Closes #123`, `Refs #456`, or full URLs.

## Runtime Diagnostics Guidance

For observability, tracing, logging, and diagnostics PRs:

- Distinguish runtime data flow from diagnostics query flow.
- State which system emits data and which system is queried later.
- When validating a successful request, query logs/traces directly.
- When validating issue detail, first create an issue or exception event.
- If two commands inspect different surfaces, explain both.

Example:

````markdown
## Manual Acceptance
1. Create a Todo through the UI.
2. Query backend request logs:

   ```bash
   curl -sS http://localhost:9428/select/logsql/query \
     -d 'query=_time:15m event_type:http_request_completed method:POST path_template:/todos' \
     -d 'limit=5'
   ```

   Expected: the latest `POST /todos` log includes a non-empty `trace_id`.

3. Query backend trace spans:

   ```bash
   curl -sS http://localhost:10428/select/jaeger/api/traces/<trace-id-from-log>
   ```

   Expected: `data` includes a backend span such as `POST /todos`.

Note: `./scripts/diagnostics issues --since 15m` lists exception issues only.
A successful Todo request appears in logs/traces, not in the issue list.
````

## GitHub CLI Notes

Prefer heredoc bodies for multiline PR descriptions:

```bash
gh pr create --title "feat(auth): add JWT token refresh" --body "$(cat <<'EOF'
## Summary
...

## What Changed
...
EOF
)"
```

If `gh pr edit` fails because of unrelated GraphQL fields, use the REST API:

```bash
gh api --method PATCH repos/<owner>/<repo>/pulls/<number> --field body="$(cat <<'EOF'
...
EOF
)"
```

## Review Checklist

- Does the PR body explain what changed and why?
- Are automated validation commands separate from manual acceptance steps?
- Do manual steps say what output proves success?
- Are diagnostics commands described with their real scope?
- Are issue-closing keywords present when appropriate?
