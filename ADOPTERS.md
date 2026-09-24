# Adopters

Using The Code Sheriff in public? Add yourself (repo, what gates you enforce).

- `pwoodman/codesheriff` — dogfoods `mode = "both"`, all gates, required check **The Code Sheriff**.
- _Your repo here_ — `mode = "local"`, `policy = "adopt"`.

# Roadmap (next, in order)

1. PyPI `codesheriff` + Docker + `action.yml` polish (install in <5 min).
2. Single-brand docs (`sheriff.toml`, `codesheriff`) with legacy aliases tested.
3. Sticky PR summary with Fix buttons (`fix-pr` discoverability).
4. Monorepo path-filtered required checks.
5. Published `eval --suite validation` scorecard (Sentry/Grafana/Keycloak) + AACR-Bench run.

Out of scope by design: hosted SaaS, editor extensions, Terraform module,
MCP server, runtime pentest/DAST/CSPM. See `COMPETITIVE_PLAN.md` focus note.
