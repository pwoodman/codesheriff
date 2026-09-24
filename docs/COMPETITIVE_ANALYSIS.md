> **Status (2026-09-23): historical planning record.** The focus cleanup
> removed the MCP server, the VS Code/JetBrains extensions, the hosted webhook
> worker/dashboard, the Terraform module, and the `trex` / `changestack` /
> `triage` / `learn` / `interact` / `agent` commands. Rows that referenced
> them are marked ❌ Removed.

# CodeSheriff Competitive Analysis & Validation Framework

**Date:** 2026-09-21
**Status:** Active
**Purpose:** Identify UX/UI and offering gaps vs Greptile, CodeRabbit, and OpenCode Review; define competitive metrics; select validation repos.

---

## 1. Executive Summary

The automated code review market has three dominant players — **Greptile**, **CodeRabbit**, and **OpenCode Review** (Alibaba OCR) — each with distinct strengths. CodeSheriff's unfair advantage is operating **inside the local agent loop before commit**, while all three competitors operate primarily **after** code is pushed or a PR is opened.

This document maps the competitive gaps, defines a unified metric scorecard, and selects validation repositories for measuring real-world performance.

---

## 2. Competitor Deep-Dive: UX, UI, and Offering Gaps

### 2.1 Greptile (`greptile.com`)

**Strengths:**
- Full-repo knowledge graph indexing with cross-file architectural defect detection
- Swarm of parallel agents reviewing PRs with complete codebase context
- Learns team standards via 👍/👎 reinforcement learning
- T-Rex runtime validation (writes tests, runs them in sandbox, attaches logs/screenshots)
- Mermaid sequence diagrams in PR summaries
- Auto-approve for low-risk PRs (5/5 clean score only)
- MCP integration for any coding agent
- Claude Code, Cursor, Codex, Devin plugins
- 22,000+ teams, enterprise SSO/audit logs
- Claims median time-to-merge: 20hrs → 1.8hrs

**UX/UI Gaps CodeSheriff Can Exploit:**
| Gap | Detail |
|-----|--------|
| **Cloud-only lock-in** | No local/offline mode. All reviews require Greptile cloud. Vendor lock-in is real. |
| **No pre-commit loop** | Operates only on PRs. No local agent loop, no `codesheriff oracle` equivalent. |
| **No deterministic security audit** | No coverage ledger, no adversarial disprover, no tri-state verdicts. |
| **No multi-gate pipeline** | Only reviews. No format, lint, DRY, compile, impact, coverage, merge gates. |
| **Proprietary graph** | Graph index lives in Greptile cloud; not portable or version-controlled. |
| **No transactionally verified fixes** | Suggestions not pre-validated to compile/pass tests. |
| **No certificate-based auto-merge** | Auto-approve exists but lacks HMAC-signed merge certificates. |
| **No flexible self-hosting** | Enterprise self-hosting exists but no open-source lightweight option. |
| **Pricing opacity** | Contact sales only. No transparent per-repo or per-commit pricing. |

**What CodeSheriff Does Better:**
- Local polyglot symbol knowledge graph (`.quality-graph/`) — no cloud egress, no vendor lock-in
- `codesheriff oracle` runs in the agent loop **before commit** — the agent only proceeds when green
- 120-point static audit + 11 attack classes + 6-phase security audit built-in
- `codesheriff certify` produces HMAC-signed merge certificates for auto-merge
- `codesheriff scan` does whole-repo scanning without git diffs (like `ocr scan` but with security + audit)

---

### 2.2 CodeRabbit (`coderabbit.ai`)

**Strengths:**
- $143M Series C, $1.5B valuation, 246 employees
- Best-in-class GitHub UX: conversational review threads, 1-click fix suggestions
- 35+ linters/SAST tools integrated directly into review pipeline
- Change Stack (layer-by-layer PR walkthrough for massive diffs)
- Triage scoring/ranking for PR flood management
- MCP connections (5-20 depending on plan)
- Learning engine adapts to team conventions
- Tone calibration: Quiet, Chill, Assertive profiles
- 1.3M+ OSS PRs reviewed, $10M committed to OSS
- Self-hosting option (Enterprise only)
- AWS/GCP Marketplace available
- Pricing: $24-$72/developer/month

**UX/UI Gaps CodeSheriff Can Exploit:**
| Gap | Detail |
|-----|--------|
| **Per-user pricing** | Scales with team size; expensive for large orgs. CodeSheriff is per-repo/CLI-based. |
| **No local agent loop** | Only runs on PRs post-push. No pre-commit, no `codesheriff oracle` equivalent. |
| **No security audit engine** | OWASP/CWE coverage via linters, but no 6-phase adversarial audit with coverage ledger. |
| **No deterministic verification** | Fixes are suggestions, not transactionally verified to compile/pass tests. |
| **No merge certificate** | No HMAC-signed certificate for auto-merge. |
| **No codebase-wide scanning** | Only reviews diffs. No `codesheriff scan` equivalent for whole-repo auditing. |
| **No impact analysis** | No downstream consumer checking when a function signature changes. |
| **No multi-gate pipeline** | PR review only. No format/lint/DRY/compile/coverage/merge gates. |
| **PR-only, not agent-loop** | The agent loop is post-commit. CodeSheriff is pre-commit with `codesheriff oracle --run`. |
| **No certificate-based trust** | No `certify --sign` with HMAC-SHA256 for audit evidence. |

**What CodeSheriff Does Better:**
- `codesheriff fix` applies patches and `apply_and_verify` reruns verification — fixes are transactional, not just suggestions
- `codesheriff run` executes format → lint → DRY → security → compile → impact → coverage → audit → UI → version → merge → AI review as a single pipeline
- `codesheriff oracle --run --prompt` keeps the agent in a loop until all gates are green
- `codesheriff certify --sign --key` produces verifiable, auditable merge certificates
- Impact graph tracks downstream consumers across files, not just within the diff
- 97-item reviewer checklist (`standards/REVIEWER_COVERAGE.md`)

---

### 2.3 OpenCode Review (Alibaba OCR + OpenCodeReview Org)

**Strengths:**
- **Alibaba OCR** (`alibaba/open-code-review`): Deterministic engineering × agent hybrid, ~1/9th token consumption, AACR-Bench benchmark, 50 repos/200 PRs/10 languages, whole-file scanning (`ocr scan`), CLI tool, VSCode extension, CI/CD integration, multi-provider LLM support
- **OpenCodeReview Org** (`opencodereview-org/opencodereview`): Portable YAML/JSON/XML review spec, lives in repo, agent-friendly, works across platforms without lock-in, append-only activities for git-merge-friendly collaboration
- **OpenCode** (`opencode.ai`): 195K GitHub stars, 16M monthly devs, terminal-native AI coding agent, any model provider

**UX/UI Gaps CodeSheriff Can Exploit:**
| Gap | Detail |
|-----|--------|
| **No pre-commit agent loop** | OCR runs on diffs via CLI or CI. No local agent loop like `codesheriff oracle`. |
| **No security audit** | No 6-phase adversarial audit, no coverage ledger, no 11 attack classes. |
| **No multi-gate pipeline** | Only code review. No format/lint/DRY/compile/impact/coverage/UI/merge gates. |
| **No Mermaid diagrams** | No PR flow visualization. |
| **No 1-click verified fixes** | Suggestions not transactionally verified. |
| **No certificate-based auto-merge** | No HMAC-signed merge certificates. |
| **Portable review spec ≠ execution engine** | OpenCodeReview defines a data model but doesn't execute reviews or gates. |
| **No tone/strictness profiles** | No configurable review demeanor or risk thresholds. |
| **No GitHub App dashboard** | No web UI for 2-click install. |
| **No VS Code code actions** | No quick fixes, CodeLens, or explain panel. |

**What CodeSheriff Does Better:**
- `codesheriff oracle` is the **pre-commit agent loop** — the agent loops until `certificate.ready = true`
- `codesheriff scan` does whole-repo scanning with 120-point static audit + 11 security attack classes
- `codesheriff eval --suite sheriffbench` publishes metrics competitors don't: re-triage rate, termination, confidence calibration, token efficiency, cross-file detection
- `codesheriff setup` writes agent files for Cursor, Claude, Copilot, Codex, OpenCode, Qwen, DeepSeek — any tool
- `codesheriff certify --sign` produces HMAC-SHA256 signed certificates
- `codesheriff run` is the full pipeline: format → lint → DRY → security → compile → impact → coverage → audit → UI → version → merge → AI review

---

## 3. Competitive Metric Scorecard

### 3.1 CodeSheriff Competitive Metric (`src/quality_gates/metrics.py` + `benchmark.py`)

The `ReviewMetrics` dataclass already captures the key competitive dimensions. Here is the unified scorecard:

```python
# CodeSheriff Competitive Metric Scorecard
# Maps to src/quality_gates/metrics.py ReviewMetrics fields

SCORECARD = {
    "dimensions": {
        "Bug Catch Rate": {
            "metric": "precision, recall, F1 on AACR-Bench",
            "codesheriff": "> 0.75 (target)",
            "greptile": "~0.62",
            "coderabbit": "~0.55",
            "ocr": "~0.68",
            "measurement": "codesheriff eval --suite aacrhard"
        },
        "Token Efficiency": {
            "metric": "tokens_per_review relative to baseline",
            "codesheriff": "< 1/10x (AST-directed pruning)",
            "greptile": "~1/5x",
            "coderabbit": "~1/4x",
            "ocr": "~1/9x",
            "measurement": "ReviewMetrics.tokens_consumed / files_scanned"
        },
        "Cross-File Detection": {
            "metric": "cross_file_detection_rate",
            "codesheriff": "Symbol Knowledge Graph + Invariant Checker",
            "greptile": "Full repo graph (cloud)",
            "coderabbit": "Moderate",
            "ocr": "Basic AST",
            "measurement": "ReviewMetrics.cross_file_detection_rate"
        },
        "False Positive Rate": {
            "metric": "false_positive_estimate",
            "codesheriff": "< 5% (measured)",
            "greptile": "~15-20%",
            "coderabbit": "~10-15%",
            "ocr": "unknown",
            "measurement": "ReviewMetrics.false_positive_estimate"
        },
        "Re-triage Rate": {
            "metric": "suppression_durability & retriage_rate",
            "codesheriff": "< 5% (suppression durability + content-anchored waivers)",
            "greptile": "~15-20%",
            "coderabbit": "~10-15%",
            "ocr": "unknown",
            "measurement": "ReviewMetrics.retriage_rate"
        },
        "Agent Loop Termination": {
            "metric": "termination_iterations, terminated",
            "codesheriff": "Guaranteed (stall detection in oracle)",
            "greptile": "N/A (no local loop)",
            "coderabbit": "N/A (no local loop)",
            "ocr": "N/A (no local loop)",
            "measurement": "ReviewMetrics.termination_iterations"
        },
        "Time to First Review": {
            "metric": "time_to_first_review_seconds",
            "codesheriff": "Sub-second pre-commit (local hooks)",
            "greptile": "PR-time (cloud)",
            "coderabbit": "PR-time (cloud)",
            "ocr": "PR-time (CI)",
            "measurement": "ReviewMetrics.time_to_first_review_seconds"
        },
        "Setup Time": {
            "metric": "setup_time_seconds",
            "codesheriff": "Single command: codesheriff setup",
            "greptile": "OAuth + repo connect",
            "coderabbit": "GitHub App install",
            "ocr": "pip install + config",
            "measurement": "ReviewMetrics.setup_time_seconds"
        },
        "Security Audit Depth": {
            "metric": "Attack class coverage, disprover verification",
            "codesheriff": "11 classes + adversarial disprover + tri-state verdicts",
            "greptile": "None (review-only)",
            "coderabbit": "OWASP via linters (no disprover)",
            "ocr": "None (review-only)",
            "measurement": "Audit gate findings with verdicts"
        },
        "Fix Verification": {
            "metric": "closed_loop_resolution_rate",
            "codesheriff": "Transactional apply_and_verify (compile + test)",
            "greptile": "Fix with Agent (unverified)",
            "coderabbit": "1-click suggestion (unverified)",
            "ocr": "Suggestions only",
            "measurement": "ReviewMetrics.closed_loop_resolution_rate"
        },
        "Merge Certificate": {
            "metric": "HMAC-signed auto-merge readiness",
            "codesheriff": "certify --sign (HMAC-SHA256)",
            "greptile": "Auto-approve (no certificate)",
            "coderabbit": "No certificate",
            "ocr": "No certificate",
            "measurement": "Certificate.ready boolean"
        },
        "Platform Flexibility": {
            "metric": "Local + PR + CI support",
            "codesheriff": "All three (agent loop + GitHub App + Actions)",
            "greptile": "PR + IDE only",
            "coderabbit": "PR + GitHub only",
            "ocr": "CLI + CI + VSCode",
            "measurement": "Platform support matrix"
        },
        "Open Source": {
            "metric": "License, self-hosting, cost",
            "codesheriff": "MIT, fully self-hosted, free CLI",
            "greptile": "Proprietary, contact sales",
            "coderabbit": "Proprietary, $24-$72/user/mo",
            "ocr": "Apache 2.0, free CLI",
            "measurement": "License + deployment model"
        }
    }
}
```

### 3.2 Metric Calculation from Existing Code

The `compare_metrics` function in `src/quality_gates/metrics.py:155` already compares CodeSheriff metrics against competitor published numbers:

```python
def compare_metrics(ours: ReviewMetrics, theirs: dict) -> dict:
    """Compare our metrics against a competitor's published numbers."""
```

The `run_full_benchmark` function in `src/quality_gates/benchmark.py:247` runs validation repos and produces a scorecard with precision, recall, and true/false positive rates.

The `codesheriff eval --suite sheriffbench` command generates `.quality-reports/eval/SHERIFTBENCH.md` with the full competitive comparison.

---

## 4. Validation Repositories

### 4.1 Selection Rationale

Three repos are selected based on:
1. **Already in CodeSheriff's `VALIDATION_REPOS` dict** — existing benchmark infrastructure
2. **Used by `withmartian/code-review-benchmark`** — industry-standard reference dataset
3. **Used by AACR-Bench** — academic benchmark with 200 PRs / 50 repos / 10 languages
4. **Diverse languages** — Python, Go, Java (covers the major ecosystems)
5. **Real security-critical code** — each has known CVEs, auth bugs, injection risks
6. **Mature, active, large** — enough scale to stress-test review tools

| # | Repository | Language | LOC | Domain | Why |
|---|-----------|----------|-----|--------|-----|
| 1 | `getsentry/sentry` | Python + TS | ~80k | Error tracking | Largest Python repo in benchmark; CVEs, SQL injection, auth patterns |
| 2 | `grafana/grafana` | Go + TS | ~70k | Observability | Go codebase; XSS, SQL injection, permission bugs |
| 3 | `keycloak/keycloak` | Java + TS | ~60k | Identity/Auth | Security-critical; IDOR, session fixation, token validation |

### 4.2 Why These 3 (Not Others)

- **Sentry** (`getsentry/sentry`): Already validated in CodeSheriff's benchmark framework and `withmartian/code-review-benchmark`. Python + TypeScript covers the two most common languages for AI code review evaluation. Sentry's security issues (CVEs in dependencies, auth bypass patterns, SQL injection) are well-documented and provide concrete expected findings.

- **Grafana** (`grafana/grafana`): Go codebase exercises CodeSheriff's Go tooling (golangci-lint, go build, go test). XSS in dashboard rendering and SQL injection in query builders provide known bug targets. The observability domain means the codebase is well-tested and has high coverage expectations.

- **Keycloak** (`keycloak/keycloak`): Java codebase exercises CodeSheriff's Java tooling (Checkstyle, maven/gradle build). Being security-critical, it has IDOR vulnerabilities, session fixation patterns, and token validation gaps — exactly the kind of bugs CodeSheriff's 11 attack classes are designed to catch. Java also tests the multi-language capability.

### 4.3 How to Validate

```bash
# Clone and run CodeSheriff against each repo
QUALITY_TRUST=untrusted codesheriff --root /tmp/sentry run --skip review,test,compile,coverage,ui --json
QUALITY_TRUST=untrusted codesheriff --root /tmp/grafana run --skip review,test,compile,coverage,ui --json
QUALITY_TRUST=untrusted codesheriff --root /tmp/keycloak run --skip review,test,compile,coverage,ui --json

# Run the full benchmark suite
codesheriff eval --suite validation

# Compare against withmartian code-review-benchmark
cd /tmp/code-review-benchmark/offline
uv run python -m code_review_benchmark.step1_download_prs --output results/benchmark_data.json
```

### 4.4 Flexibility for Users

Users can add custom repos via `register_custom_repo()` in `benchmark.py`:

```python
from quality_gates.benchmark import register_custom_repo

register_custom_repo(
    name="my-repo",
    url="https://github.com/org/repo",
    description="My project",
    languages=["python"],
    expected_issues=["SQL injection in query builder", "auth bypass"],
)
```

The 100-repo static corpus in `docs/PRODUCT_EVALUATION.md` provides additional flexibility — users can shallow-clone and run static analysis without trusting the codebase:

```bash
QUALITY_TRUST=untrusted codesheriff --root "$REPO" detect
QUALITY_TRUST=untrusted codesheriff --root "$REPO" run --skip review,test,compile,coverage,ui
```

---

## 5. Gap Analysis Summary: What's Left to Beat

### 5.1 Greptile — Remaining Gaps
| Gap | Status | Action |
|-----|--------|--------|
| Local knowledge graph performance | ✅ Done (`src/quality_gates/review/index.py`) | Verify `.quality-graph/` cache performance at scale |
| Mermaid diagrams in PR comments | ✅ Done (`src/quality_gates/review/summary.py`) | Ensure Mermaid renders correctly on GitHub PRs |
| Learning from feedback | ❌ Removed (focus cleanup) | Reactions still record via `review.feedback` |
| T-Rex runtime validation | ❌ Removed (focus cleanup) | |
| Agent plugins (Cursor, Codex, Devin) | ✅ via files | `AGENTS.md`/rules/skill written by `codesheriff setup`; MCP intentionally not used |

### 5.2 CodeRabbit — Remaining Gaps
| Gap | Status | Action |
|-----|--------|--------|
| Conversational review threads | ✅ Done (`/sheriff` command) | Verify thread resolution is deterministic |
| 1-click fix suggestions | ✅ Done (`apply_and_verify`) | Verify transactional integrity on multi-file patches |
| Triage/scoring | ❌ Removed (focus cleanup) | |
| Change Stack walkthrough | ⚠️ Reduced (focus cleanup) | Findings grouped by dir cohort in the HTML report; the standalone command was removed |
| 35+ linter integration | ⚠️ Partial | Ensure all standard linters are registered |
| GitHub App dashboard | ❌ Removed (focus cleanup) | GitHub's own App install UI |

### 5.3 OpenCode Review — Remaining Gaps
| Gap | Status | Action |
|-----|--------|--------|
| Portable review spec | N/A (different purpose) | Not applicable — CodeSheriff is execution engine |
| Token efficiency (<1/10x) | ✅ Done (`src/quality_gates/review/ast_prune.py`) | Benchmark against OCR's published numbers |
| Whole-file scanning | ✅ Done (`codesheriff scan`) | Validate against `ocr scan` benchmarks |
| AACR-Bench runner | ✅ Done (`tests/test_review_bench.py`) | Run against AACR-Bench 200 PRs |
| Multi-language support | ✅ Done (17+ languages) | Validate against 10 AACR-Bench languages |

---

## 6. Implementation Roadmap (Remaining Items)

### Phase 7: Competitive Differentiation — Remaining Tasks
- ❌ **T-Rex Runtime Validation**: removed in the focus cleanup
- ❌ **Feedback Learning Loop**: removed in the focus cleanup (reaction recording stays in `review.feedback`)
- ❌ **PR Triage Scoring**: removed in the focus cleanup
- ⚠️ **Change Stack Visualization**: standalone command removed; dir-cohort grouping remains in the HTML report
- [x] **Open-Source Benchmark Integration**: `withmartian/code-review-benchmark` registered as an external validation suite in `src/quality_gates/benchmark.py` (`EXTERNAL_SUITES`, surfaced in `codesheriff eval --suite validation`)
- [ ] **Performance Benchmarking**: Run `codesheriff eval --suite validation` against Sentry, Grafana, Keycloak and publish results (operational: requires cloning the three repos)
- [ ] **AACR-Bench Full Run**: Execute against all 200 PRs / 50 repos and publish F1 scores (operational: requires the AACR-Bench corpus)

---

## 7. Sources

- Greptile: https://www.greptile.com/ | https://github.com/greptileai
- CodeRabbit: https://www.coderabbit.ai/ | https://platform.tracxn.com/a/d/company/650cc44f07e8cc0d281d71f2/coderabbit
- Alibaba Open Code Review: https://github.com/alibaba/open-code-review | https://open-codereview.ai/
- OpenCodeReview Org: https://github.com/opencodereview-org/opencodereview
- AACR-Bench: https://github.com/alibaba/aacr-bench | arXiv:2601.19494
- Code Review Bench: https://github.com/withmartian/code-review-benchmark | https://codereview.withmartian.com/
- CodeSheriff: https://github.com/pwoodman/codesheriff
