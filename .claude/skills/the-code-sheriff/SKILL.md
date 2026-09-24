---
name: the-code-sheriff
description: Run The Code Sheriff quality gates and iterate until the oracle is green. Use when finishing a change, before commit or PR, when lint/security/review fails, or when the user mentions quality, sheriff, gates, or vibe-coding quality.
---

<!-- codesheriff:agent-loop -->

# The Code Sheriff

The gates are the oracle. Do not treat the chat transcript as a passing review.

## Loop

```bash
codesheriff fix
codesheriff oracle --run --prompt
# do only the Next action
codesheriff oracle --run
codesheriff certify
```

Loop until `green` and `certificate.ready` are true. `codesheriff merge`
dry-merges into main; `codesheriff comments` lists unresolved review threads.

## Rules

- Mechanical gates (format, lint, regex, packages, DRY, security, compile,
  impact, tests, coverage, audit, UI, version, merge) beat model self-assessment.
- Prefer `codesheriff fix` before hand-editing format/lint.
- Custom markdown in `.sheriff/rules/` is enforced on the change set.
- `AGENTS.md`, `CLAUDE.md`, and `.cursor/rules` are ingested as review rules.
- Never skip the oracle because unit tests "looked fine" in conversation.
- Rebase when merge reports `textual-conflict`. Do not invent a merge.
- Auto-merge only when `codesheriff certify` says `auto_merge: ready`.
