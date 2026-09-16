# CodeSheriff product evaluation

This is a hypothetical usability review, not feedback from Google, Meta, xAI,
Apple, PayPal, or their employees. It simulates a lead engineer and a senior
engineer at each company using publicly known engineering priorities: scale and
developer velocity, privacy, AI safety, platform consistency, and regulated
payments. Treat it as a product-discovery input to validate with actual users.

## Simulated feedback

| Persona | Lead engineer perspective | Senior engineer perspective |
| --- | --- | --- |
| Google | Policy must be declarative, centrally managed, and measurable across a monorepo. | Local iteration needs a fast, explainable plan and Bazel-aware targets. |
| Meta | Suppressions need ownership, expiry, and fleet-level trend reporting. | Diff feedback must be low-noise and never obscure the next actionable fix. |
| xAI | Agent actions need tool-call traces, deterministic replay, and a clear trust boundary. | The agent loop should expose structured evidence, not only prose. |
| Apple | Default collection must be minimal; reports cannot leak paths or source outside a developer-controlled environment. | Native toolchain diagnostics and offline operation matter more than SaaS integration. |
| PayPal | Every exception needs an approver, expiry, and immutable audit evidence. | Payment-sensitive changes need risk-based checks without making ordinary changes slow. |

## Ten improvements

1. Add organization policy bundles with signed versions and repo-level override
   explanations.
2. Add a monorepo target resolver for Bazel, Buck, Gradle, and workspace tools.
3. Give every finding a stable fingerprint, owner, expiry, and remediation state.
4. Emit a machine-readable agent trace containing command, input scope, evidence,
   and trust decision.
5. Add a redaction policy preview before writing or uploading reports.
6. Offer a fully offline tool-manifest mode with an explicit stale-data signal.
7. Classify payment, authentication, and authorization paths as high-risk zones.
8. Show one ranked next action with estimated runtime and expected gate impact.
9. Record suppression approvals in an append-only local and exportable ledger.
10. Publish false-positive and time-to-green metrics by rule, language, and repo.

## Ten new features

1. `codesheriff policy verify` for signed policy bundles.
2. Monorepo target adapters with changed-target and affected-test selection.
3. `codesheriff trace export` for deterministic agent-run replay.
4. A redaction simulator for reports, diagnostics, and PR comments.
5. Offline cache provenance and expiration inspection.
6. Risk-zone rules for PCI-like data flow, auth, and privileged operations.
7. Finding ownership routing from CODEOWNERS and team maps.
8. Time-budgeted plans that stop before an agreed local or CI deadline.
9. SARIF baseline import/export with suppression ownership and expiry.
10. A privacy-preserving fleet metrics exporter with opt-in aggregation.

## Ten complexity reductions

1. Keep `codesheriff` as the only documented executable; retain `quality` only
   as a compatibility shim.
2. Use `codesheriff_*` as the only documented MCP tool namespace.
3. Keep the established `[quality]` configuration schema during the transition.
4. Generate every agent integration from one canonical template.
5. Present one primary command, `codesheriff run`, before advanced subcommands.
6. Collapse gate explanations into a single ordered playbook.
7. Default unknown repositories to static-only, untrusted operation.
8. Make missing tools visible skips with install guidance instead of implicit fallbacks.
9. Use one report directory and one stable JSON report contract.
10. Keep AI review advisory by default and separate it from mechanical gate status.

## Static corpus

The corpus has 100 real GitHub repositories across ten primary language
ecosystems. Clone shallowly and run only static, untrusted commands; do not run
their builds, tests, package scripts, or plugins without an explicit code review
and trusted-execution approval.

```bash
git clone --depth 1 "https://github.com/OWNER/REPO.git" "$REPO"
QUALITY_TRUST=untrusted codesheriff --root "$REPO" detect
QUALITY_TRUST=untrusted codesheriff --root "$REPO" run --skip review,test,compile,coverage,ui
```

| Primary language | Repositories |
| --- | --- |
| Python | psf/requests, pallets/flask, django/django, fastapi/fastapi, pydantic/pydantic, pytest-dev/pytest, scikit-learn/scikit-learn, ansible/ansible, apache/airflow, numpy/numpy |
| JavaScript | nodejs/node, facebook/react, vuejs/core, angular/angular, sveltejs/svelte, expressjs/express, lodash/lodash, vitejs/vite, vercel/next.js, nestjs/nest |
| TypeScript | microsoft/TypeScript, denoland/deno, prisma/prisma, mui/material-ui, ionic-team/ionic-framework, reduxjs/redux, eslint/eslint, microsoft/vscode, appwrite/appwrite, typeorm/typeorm |
| Go | kubernetes/kubernetes, golang/go, prometheus/prometheus, hashicorp/terraform, docker/cli, gin-gonic/gin, grpc/grpc-go, caddyserver/caddy, grafana/loki, helm/helm |
| Rust | rust-lang/rust, tokio-rs/tokio, serde-rs/serde, rust-lang/cargo, bevyengine/bevy, sharkdp/bat, BurntSushi/ripgrep, rust-lang/rustlings, diesel-rs/diesel, servo/servo |
| Java | spring-projects/spring-framework, apache/kafka, elastic/elasticsearch, google/guava, junit-team/junit5, apache/maven, gradle/gradle, quarkusio/quarkus, checkstyle/checkstyle, apache/cassandra |
| C# | dotnet/runtime, dotnet/aspnetcore, dotnet/roslyn, dotnet/efcore, AvaloniaUI/Avalonia, Unity-Technologies/UnityCsReference, OrchardCMS/OrchardCore, ElsaWorkflows/elsa-core, DapperLib/Dapper, graphql-dotnet/graphql-dotnet |
| C++ | llvm/llvm-project, google/googletest, protocolbuffers/protobuf, opencv/opencv, tensorflow/tensorflow, electron/electron, microsoft/terminal, fmtlib/fmt, catchorg/Catch2, nlohmann/json |
| Ruby | rails/rails, ruby/ruby, discourse/discourse, fastlane/fastlane, Homebrew/brew, spree/spree, jekyll/jekyll, ruby-grape/grape, chef/chef, sidekiq/sidekiq |
| PHP | laravel/laravel, symfony/symfony, composer/composer, wordpress/wordpress, sebastianbergmann/phpunit, doctrine/orm, guzzle/guzzle, nextcloud/server, magento/magento2, laravel/framework |

## MVP implementation status

The MVP keeps `codesheriff` as the public command and retains the `quality`
entry point only as a compatibility shim. It adds local, machine-readable
utilities without changing the established `[quality]` configuration contract:

- `codesheriff policy verify --bundle POLICY.json --key KEY` verifies a
  canonical HMAC-SHA256 policy bundle. The signing key is supplied locally (or
  by `QUALITY_POLICY_KEY`) and is never written to a report.
- `codesheriff trace export`, `codesheriff redact --input REPORT`, and
  `codesheriff cache status --provenance` respectively export structured gate
  evidence, preview secret/key redaction without writing it, and expose local
  cache provenance and age/staleness.
- `codesheriff risk --paths ...`, `codesheriff sarif import-baseline`, and
  `codesheriff sarif export-baseline` provide risk-zone labels and portable
  baseline records with stable fingerprints and CODEOWNERS inference.
- `codesheriff fleet export --opt-in` writes only rule/language/severity
  aggregates: no source, paths, messages, identities, or automatic upload.
- `codesheriff run --plan --time-budget-seconds N` shows estimated execution
  time and defers only advisory checks; required checks are never deferred.
- `codesheriff targets --paths ...` selects already-discovered workspace
  boundaries for a changed package. It is selection-only in this MVP: it does
  not invoke Bazel, Buck, Gradle, or any repository task.

Suppressions already require reason, optional owner, and expiry in
`.quality/ignore.toml`. The local finding ledger now records suppression owner,
reason, expiry, timestamp, and an append-only event entry.

`codesheriff benchmark --root CHECKOUT` inventories supplied corpus checkouts
using language detection only. It does not clone repositories, invoke package
managers, run builds/tests/scripts/plugins, or execute untrusted repository
code. The table above is the static 100-repository corpus manifest; benchmark
results are therefore static-only MVP evidence, not build compatibility claims.
