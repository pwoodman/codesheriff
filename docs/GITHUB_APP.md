# The Code Sheriff

**The Code Sheriff is a free GitHub App.** There is no hosted service: gates
run on **that repository's own GitHub Actions minutes**, the webhook is off by
default, and no data leaves your runners. This project dogfoods the same check
via [`.github/workflows/sheriff.yml`](../.github/workflows/sheriff.yml).

GitHub slugifies the App name (typically `the-code-sheriff`). Checks and
branch protection still use **The Code Sheriff**. CLI is `codesheriff`
(`quality` remains a compatibility alias).

There are two ways to use Sheriff on a repository — the workflow (works today,
no App required) and the App (one durable check + `/sheriff` commands).

## One command (workflow, no App required)

In the repo you want to scan:

```bash
uvx codesheriff setup
```

That writes a default `sheriff.toml`, pins `.github/workflows/quality.yml`,
adds git hooks, creates a ruleset requiring **The Code Sheriff** when `gh` is
logged in, and records a baseline. Commit those files.

`codesheriff init` writes the files without running gates or touching GitHub
rules.

## Install the App (free)

Install URL:

```
https://github.com/apps/the-code-sheriff/installations/new
```

Installing the App gives you:

- One durable required check named **The Code Sheriff** (posted with
  least-privilege permissions).
- `/sheriff …` PR comment commands (`/sheriff review`, `/sheriff explain`,
  `/sheriff fix`, `/sheriff help`).
- Installation tokens so checks post as the App bot instead of
  `github-actions[bot]` when `QUALITY_APP_ID` and `QUALITY_APP_PRIVATE_KEY`
  are set as repo/org secrets.

Permissions (least privilege):

| Permission | Access | Why |
| --- | --- | --- |
| checks | write | One durable check named **The Code Sheriff** |
| pull_requests | write | Inline comments, suggested changes, PR summary |
| contents | read | Source, CODEOWNERS, workflows |
| metadata | read | Installation and private/public visibility |
| security_events | write | Attach secret/SCA alerts |

Events: `pull_request`, `check_run`, `check_suite`, `issue_comment`
(`/sheriff …` commands). `hook_attributes.active = false` — GitHub does not
deliver webhooks until you point one at your own receiver, and you never need
one: the check is produced by the installed repository's Actions workflow.

## Auto-merge when Sheriff is green

After the required check exists:

```bash
codesheriff setup --auto-merge
```

That sets `allow_auto_merge` on the GitHub repo. On each PR, click **Enable
auto-merge**. The PR lands only when **The Code Sheriff** is green.
`codesheriff certify` writes `.quality-reports/certificate.json` with
`auto_merge: ready` only after every required gate passed and unresolved
review threads are gone. That is the "no fear" signal — not chat confidence.

Fork PRs stay `untrusted`. LLM keys stay in that repo's secrets if you want
model review; the default GitHub Copilot reviewer uses GitHub's own access.
Without any key, heuristic review still runs — the App stays free.

## Publishing the App (maintainers)

The manifest lives at [`github-app/manifest.json`](../github-app/manifest.json)
(public, webhook inactive, redirect to localhost for registration). To (re)create
the App on GitHub:

```bash
codesheriff github-app register     # opens GitHub's manifest-flow URL
codesheriff github-app manifest      # print the manifest payload
```

Credentials land in `.quality-app/` (gitignored). After creation:

1. Keep the webhook **inactive** — no receiver is required or shipped.
2. Create the Marketplace/listing metadata on the app page (free, open-source
   listing); the install URL above already works without it.
3. Set `HOMEPAGE`/`url` to `https://github.com/pwoodman/codesheriff`.

Installation tokens are the default identity when `QUALITY_APP_ID` and
`QUALITY_APP_PRIVATE_KEY` are set. Optional: store them as org secrets so
checks post as the App bot. The required check name is still **The Code
Sheriff**.

GitHub Enterprise Server: set `GITHUB_API_URL`. Delivery diagnostics (for any
receiver you operate yourself): `codesheriff github-app deliveries`.

## Telemetry

Off.
