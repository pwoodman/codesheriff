# Install The Code Sheriff

One command on a new repo (writes `sheriff.toml`, workflow, hooks, baseline):

```bash
uvx codesheriff setup
```

`quality.toml` / `quality` remain accepted as legacy aliases. Prefer `sheriff.toml` / `codesheriff`.

## Options (pick one)

```bash
# Latest release, isolated (recommended)
uvx codesheriff setup
uv tool install codesheriff && codesheriff setup

# pipx / pip
pipx install codesheriff && codesheriff setup
pip install codesheriff && codesheriff setup

# From source (unreleased main)
uvx --from git+https://github.com/pwoodman/codesheriff.git codesheriff setup

# Docker (batteries-included: node, prettier, eslint, jscpd, shellcheck)
docker build -t codesheriff .
docker run --rm -v "$PWD:/repo" -w /repo codesheriff run --skip review

# GitHub Action (Marketplace-style composite)
# - uses: pwoodman/codesheriff@v1
#   with: { args: "run" }
```

## Toolchains

Gates never install tools. Install once, explicitly:

```bash
codesheriff doctor            # what is missing for this repo
codesheriff doctor --install  # pinned gitleaks, osv-scanner, golangci-lint, JS tooling
# or: codesheriff doctor --fix (same as --install)
```

Everything else (ruff, go, rustfmt, JDK, .NET, PHP, Ruby) comes from your
platform package manager or project bundle. Missing tools report `skip`,
never silent pass.

## First run

```bash
codesheriff setup --dry-run   # preview, writes nothing
codesheriff setup             # adopt policy: old debt baselined, new issues block
codesheriff fix
codesheriff oracle --run --prompt
codesheriff certify
```

Untrusted clones (OSS you do not own): prefix `QUALITY_TRUST=untrusted` and
skip execution gates — see `docs/BETA_TESTING.md`.
