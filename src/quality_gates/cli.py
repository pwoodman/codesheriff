from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from quality_gates import GATES, __version__, cli_ext
from quality_gates import gates as gate_runners
from quality_gates.change_manifest import discover_changes
from quality_gates.ci_plan import (
    risk_decision,
    select_change_gates,
    select_gates,
    unknown_gates,
)
from quality_gates.cli_runtime import (
    _apply_one,
    _baseline,
    _certify,
    _csv,
    _emit,
    _eval,
    _fix,
    _onboard,
    _oracle,
    _print_detect,
    _resolve_languages,
    _watch,
)
from quality_gates.config import is_pr_event, load_config
from quality_gates.detect import detect_languages
from quality_gates.doctor import doctor
from quality_gates.evidence import attach_evidence
from quality_gates.gates.version import apply_bump
from quality_gates.paths import cache_dir, project_root
from quality_gates.planner import build_plan, render_plan, write_plan
from quality_gates.report_cli import print_report as _print_report
from quality_gates.result_cache import cache_status, clean_cache


def _invoked_as_sheriff(argv: Sequence[str] | None) -> bool:
    if argv is not None:
        return False
    name = Path(sys.argv[0]).name.lower().replace("_", "-")
    return name in {"codesheriff", "the-codesheriff"} or name.startswith("codesheriff")


def _invoked_as_legacy_quality(argv: Sequence[str] | None) -> bool:
    return argv is None and Path(sys.argv[0]).name.lower() == "quality"


# Phase 1.3: the top-level surface is the everyday loop. Everything else is
# still reachable, but grouped so `codesheriff --help` reads like a product
# instead of a tool dump. The groups are argv rewrites, so every existing
# parser, test, and muscle-memory invocation keeps working unchanged.
ADMIN_COMMANDS = frozenset(
    {
        "apply",
        "baseline",
        "benchmark",
        "bump",
        "cache",
        "eval",
        "evidence",
        "fleet",
        "github-app",
        "ingest",
        "init",
        "merge",
        "notes",
        "policy",
        "redact",
        "reports",
        "risk",
        "rules",
        "sarif",
        "sbom",
        "setup",
        "targets",
        "timing",
        "trace",
        "watch",
    }
)
DEBUG_COMMANDS = frozenset(
    {
        "check-local",
        "comments",
        "detect",
        "doctor",
        "ignore",
        "mcp",
        "packages",
        "regex",
        "serve",
        "ui",
        "version",
    }
)
DEPRECATED_ALIASES = {
    "check": "review",
}


def _rewrite_argv(argv: Sequence[str]) -> tuple[list[str], str | None]:
    """Expand a leading ``admin``/``debug`` group or deprecated alias."""
    items = list(argv)
    if not items:
        return items, None
    command = items[0]
    if command in DEPRECATED_ALIASES:
        print(
            f"warning: `{command}` is deprecated; use `{DEPRECATED_ALIASES[command]}`.",
            file=sys.stderr,
        )
        items[0] = DEPRECATED_ALIASES[command]
        return items, None
    if command in {"admin", "debug"}:
        items.pop(0)
        return items, command
    return items, None


def _group_help(group: str) -> int:
    names = sorted(ADMIN_COMMANDS if group == "admin" else DEBUG_COMMANDS)
    print(f"codesheriff {group} — grouped commands (equal to running them directly):")
    for name in names:
        print(f"  codesheriff {name}")
    print(f"\nrun `codesheriff {group} <command> [args]` or `codesheriff <command>`")
    return 0


def _add_onboard_args(
    parser: argparse.ArgumentParser,
    *,
    require_check: bool,
    hooks: bool = False,
    run: bool = False,
    agents: bool = False,
) -> None:
    parser.add_argument(
        "--org",
        default="",
        help="GitHub owner of a The Code Sheriff fork (default: pwoodman)",
    )
    parser.add_argument(
        "--source",
        default="",
        help="owner/repo that hosts the reusable workflow (default: pwoodman/the-code-sheriff)",
    )
    parser.add_argument(
        "--pin",
        default="auto",
        help="commit SHA or git ref to pin; auto resolves main",
    )
    parser.add_argument(
        "--policy",
        dest="init_policy",
        choices=["observe", "adopt", "enforce"],
        default="adopt",
        help="PR-blocking policy for the new repo (default adopt)",
    )
    parser.add_argument(
        "--vendor-cli",
        action="store_true",
        help="also write a pip-install workflow instead of only the reusable one",
    )
    parser.add_argument(
        "--require-check",
        action=argparse.BooleanOptionalAction,
        default=require_check,
        help="create a GitHub ruleset requiring The Code Sheriff",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite sheriff.toml and generated workflows",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print what setup would write without touching the repo",
    )
    parser.add_argument(
        "--hooks",
        action=argparse.BooleanOptionalAction,
        default=hooks,
        help="write .pre-commit-config.yaml and try pre-commit install",
    )
    parser.add_argument(
        "--run",
        action=argparse.BooleanOptionalAction,
        default=run,
        help="run gates once and write .sheriff-baseline.json",
    )
    parser.add_argument(
        "--agents",
        action=argparse.BooleanOptionalAction,
        default=agents,
        help="write Cursor/Claude MCP, rule, and skill so agents loop on codesheriff oracle",
    )
    parser.add_argument(
        "--auto-merge",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="enable GitHub repo auto-merge so green Sheriff PRs can land",
    )
    parser.add_argument(
        "--ai",
        choices=["auto", "github-copilot"],
        default="auto",
        help="AI provider for setup (github-copilot uses GitHub's native reviewer)",
    )


def main(argv: Sequence[str] | None = None) -> int:
    argv, group = _rewrite_argv(sys.argv[1:] if argv is None else argv)
    if group is not None and not argv:
        return _group_help(group)
    parser = argparse.ArgumentParser(
        prog="codesheriff",
        description="Multi-language format, lint, DRY, security, compile, impact, coverage, 120-point audit, UI, version, and AI review gates.",
        epilog=(
            "common commands:\n"
            "  setup      install Sheriff into this repo (config, workflow, hooks)\n"
            "  run        run the change-aware gate suite (the everyday command)\n"
            "  fix        apply safe automatic remediations\n"
            "  oracle     remaining blockers + one Next action (agent loop)\n"
            "  report     reprint the last run's scorecard\n"
            "  doctor     diagnose missing tools\n"
            "  certify    merge certificate (auto-merge readiness)\n"
            "\n"
            "groups:\n"
            "  admin      setup, baseline, merge, eval, sbom, fleet, policy, ...\n"
            "  debug      doctor, detect, serve, ui, rules, traces, ...\n"
            "\n"
            "everything else is diagnostics or administration; run\n"
            "`codesheriff <command> --help` for details."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    if _invoked_as_legacy_quality(argv):
        print(
            "warning: `quality` is a compatibility command; use `codesheriff`.",
            file=sys.stderr,
        )
    parser.add_argument(
        "--version", action="version", version=f"The Code Sheriff {__version__}"
    )
    parser.add_argument(
        "--root", type=Path, default=None, help="project root (default: cwd / git root)"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--policy",
        choices=["observe", "adopt", "enforce"],
        default=None,
        help="observe = report only; adopt = ratchet vs baseline; enforce = fail_on (default: sheriff.toml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("detect", help="list languages and toolchains in the project")
    doctor_parser = sub.add_parser("doctor", help="show which tools are available")
    doctor_parser.add_argument(
        "--install", action="store_true", help="download pinned CI binaries"
    )
    cache_p = sub.add_parser("cache", help="inspect or clean deterministic results")
    cache_p.add_argument(
        "action", choices=["status", "clean"], nargs="?", default="status"
    )
    cache_p.add_argument(
        "--provenance",
        action="store_true",
        help="include local cache age and provenance",
    )

    policy_p = sub.add_parser(
        "policy", help="verify a signed organization policy bundle"
    )
    policy_cmd = policy_p.add_subparsers(dest="policy_command", required=True)
    policy_verify = policy_cmd.add_parser(
        "verify", help="verify an HMAC-SHA256 policy bundle"
    )
    policy_verify.add_argument("--bundle", type=Path, required=True)
    policy_verify.add_argument(
        "--key", default=None, help="signing key (or QUALITY_POLICY_KEY)"
    )

    trace_p = sub.add_parser("trace", help="export structured local agent evidence")
    trace_cmd = trace_p.add_subparsers(dest="trace_command", required=True)
    trace_export = trace_cmd.add_parser(
        "export", help="write a deterministic trace JSON"
    )
    trace_export.add_argument("--output", type=Path, default=None)

    redact_p = sub.add_parser(
        "redact", help="preview report redaction without writing output"
    )
    redact_p.add_argument("--input", type=Path, default=None)

    risk_p = sub.add_parser(
        "risk", help="show changed-file auth, authorization, and payment zones"
    )
    risk_p.add_argument(
        "--paths", default="", help="comma-separated repository-relative paths"
    )

    sarif_p = sub.add_parser(
        "sarif", help="import or export baseline findings with metadata"
    )
    sarif_cmd = sarif_p.add_subparsers(dest="sarif_command", required=True)
    sarif_import = sarif_cmd.add_parser("import-baseline", help="read a SARIF baseline")
    sarif_import.add_argument("--input", type=Path, required=True)
    sarif_export = sarif_cmd.add_parser(
        "export-baseline", help="write a SARIF baseline"
    )
    sarif_export.add_argument("--output", type=Path, default=None)

    fleet_p = sub.add_parser(
        "fleet", help="export opt-in privacy-preserving fleet metrics"
    )
    fleet_cmd = fleet_p.add_subparsers(dest="fleet_command", required=True)
    fleet_export = fleet_cmd.add_parser(
        "export", help="write aggregate metrics without source data"
    )
    fleet_export.add_argument("--output", type=Path, default=None)
    fleet_export.add_argument(
        "--opt-in", action="store_true", help="confirm local metrics export"
    )
    fleet_report = fleet_cmd.add_parser(
        "report", help="org-wide rollup across sibling checkouts (local only)"
    )
    fleet_report.add_argument(
        "--scan", type=Path, default=None, help="directory holding sibling checkouts"
    )
    fleet_report.add_argument(
        "--format", choices=["markdown", "json"], default="markdown"
    )
    fleet_report.add_argument("--output", type=Path, default=None)

    benchmark_p = sub.add_parser(
        "benchmark", help="static-only OSS checkout corpus inventory"
    )
    benchmark_p.add_argument(
        "--root", dest="benchmark_roots", action="append", type=Path
    )
    targets_p = sub.add_parser(
        "targets", help="select affected existing monorepo workspaces"
    )
    targets_p.add_argument("--paths", default="", help="comma-separated changed paths")

    fmt = sub.add_parser("format", help="run formatters")
    fmt.add_argument("--check", action="store_true", default=True)
    fmt.add_argument(
        "--write", action="store_true", help="apply formatting instead of checking"
    )
    fmt.add_argument("--language", action="append", dest="languages")

    lint = sub.add_parser("lint", help="run linters")
    lint.add_argument("--language", action="append", dest="languages")

    regex_p = sub.add_parser("regex", help="regex checker over the change set")
    regex_p.add_argument("--base", default=None)
    packages_p = sub.add_parser(
        "packages",
        help="risky/undeclared packages from imports and new dependencies",
    )
    packages_p.add_argument("--base", default=None)

    sub.add_parser("dry", help="copy-paste / duplication scan")
    sub.add_parser("dead", help="find unused Python code")
    sub.add_parser(
        "security",
        help="secrets, SCA, SAST, IaC misconfig, SBOM (gitleaks/osv/semgrep/trivy/checkov)",
    )
    sbom_p = sub.add_parser(
        "sbom",
        help="write CycloneDX and SPDX SBOMs under .quality-reports",
    )
    sbom_p.add_argument(
        "--format",
        dest="sbom_format",
        choices=["all", "cyclonedx", "spdx"],
        default="all",
    )
    compile_p = sub.add_parser(
        "compile",
        help="build compiled languages (only after a clean security gate)",
    )
    compile_p.add_argument("--language", action="append", dest="languages")
    compile_p.add_argument(
        "--force",
        action="store_true",
        help="compile even if security has not passed (not recommended)",
    )
    version_p = sub.add_parser("version", help="semver consistency and required bumps")
    version_p.add_argument("--base", default=None)

    bump = sub.add_parser("bump", help="write a semver bump into version files")
    bump.add_argument(
        "part",
        choices=["auto", "major", "minor", "patch"],
        help="auto uses conventional commits since the base ref",
    )

    review = sub.add_parser("review", help="AI / heuristic code review")
    review.add_argument("--base", default=None, help="git ref to diff against")
    review.add_argument(
        "--post",
        action="store_true",
        help="post inline review comments and a check run",
    )

    eval_p = sub.add_parser(
        "eval",
        help="ReviewBench scorecard; optional Martian / Macroscope comparison",
    )
    eval_p.add_argument(
        "--suite",
        dest="eval_suite",
        choices=["reviewbench", "sheriffbench", "martian", "macroscope", "all"],
        default="reviewbench",
    )
    eval_p.add_argument(
        "--download",
        action="store_true",
        help="fetch Martian golden comments (MIT) into .quality-reports/eval",
    )
    eval_p.add_argument(
        "--llm",
        action="store_true",
        help="require a live LLM (QUALITY_REVIEW_EVAL / provider key)",
    )

    oracle_p = sub.add_parser(
        "oracle",
        help="remaining blockers for coding agents (loop until green)",
    )
    oracle_p.add_argument(
        "--run",
        action="store_true",
        help="run gates first, then report what is still blocking",
    )
    oracle_p.add_argument(
        "--prompt",
        action="store_true",
        help="print a fix-it prompt instead of JSON",
    )
    oracle_p.add_argument("--only", default=None, help="comma-separated gates")
    oracle_p.add_argument("--skip", default=None, help="comma-separated gates")
    oracle_p.add_argument("--full", action="store_true")
    oracle_p.add_argument("--base", default=None)
    oracle_p.add_argument(
        "--reset-stall",
        action="store_true",
        help="clear the repeated-next-action counter before evaluating",
    )

    sub.add_parser(
        "mcp",
        help=(
            "MCP stdio server: codesheriff_oracle, codesheriff_run, "
            "codesheriff_review, codesheriff_merge, codesheriff_pr_comments, "
            "codesheriff_finding_context, codesheriff_apply_fix, "
            "codesheriff_fix, codesheriff_certify"
        ),
    )

    fix_p = sub.add_parser(
        "fix",
        help="safe auto-fixes: format --write, ruff --fix, finding patches",
    )
    fix_p.add_argument(
        "--no-patches",
        action="store_true",
        help="skip applying finding patches; only format/lint autofix",
    )

    certify_p = sub.add_parser(
        "certify",
        help="print the merge certificate (auto-merge ready when green)",
    )
    certify_p.add_argument(
        "--sign",
        action="store_true",
        help="attach an HMAC-SHA256 signature (key from --key or SHERIFF_CERT_KEY)",
    )
    certify_p.add_argument(
        "--key", default=None, help="signing key (or SHERIFF_CERT_KEY)"
    )
    certify_p.add_argument(
        "--verify", action="store_true", help="verify the stored certificate signature"
    )

    apply_p = sub.add_parser(
        "apply",
        help="apply one finding patch by id from the last oracle report",
    )
    apply_p.add_argument("--id", dest="finding_id", default=None)

    ui_p = sub.add_parser(
        "ui",
        help="selective Playwright/Cypress tests for files changed vs --base",
    )
    ui_p.add_argument(
        "--list",
        action="store_true",
        help="print which specs would run, without launching a browser",
    )
    ui_p.add_argument(
        "--all",
        action="store_true",
        help="run every spec instead of selecting from the diff",
    )
    ui_p.add_argument("--base", default=None, help="git ref to diff against")

    impact_p = sub.add_parser(
        "impact",
        help="upstream/downstream impact: who uses this change, and is it validated",
    )
    impact_p.add_argument("--base", default=None, help="git ref to diff against")

    merge_p = sub.add_parser(
        "merge",
        help=(
            "dry-merge vs the base branch: textual conflicts, optional "
            "sibling PRs, optional compile/impact verify"
        ),
    )
    merge_p.add_argument(
        "--base",
        default=None,
        help="git ref to merge into (default origin/main)",
    )
    merge_p.add_argument(
        "--verify",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="after a clean merge-tree, compile/impact the merged tree",
    )
    merge_p.add_argument(
        "--siblings",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="also merge-tree against other open PR heads",
    )

    comments_p = sub.add_parser(
        "comments",
        help=(
            "list unresolved GitHub review threads for the current PR "
            "(oracle remaining work)"
        ),
    )
    comments_p.add_argument(
        "--fail",
        action="store_true",
        help="exit 1 when unresolved threads remain (default: report only)",
    )

    sub.add_parser(
        "coverage",
        help="test coverage vs configurable floor (default 80%% lines)",
    )
    test_p = sub.add_parser(
        "test", help="run unit tests, require tests for source, track timing"
    )
    test_p.add_argument("--base", default=None)

    ignore_p = sub.add_parser(
        "ignore", help="override a finding (writes .quality/ignore.toml)"
    )
    ignore_p.add_argument("action", choices=["add"])
    ignore_p.add_argument("--rule", required=True)
    ignore_p.add_argument("--path", default=None)
    ignore_p.add_argument("--gate", default=None)
    ignore_p.add_argument("--reason", required=True)
    ignore_p.add_argument("--owner", default="")
    ignore_p.add_argument("--days", type=int, default=90)

    timing_p = sub.add_parser(
        "timing", help="accept a test duration baseline after a regression alert"
    )
    timing_p.add_argument("action", choices=["accept"])
    timing_p.add_argument("--test", action="append", dest="tests")
    timing_p.add_argument(
        "--all-regressed",
        action="store_true",
        help="accept every currently flagged timing regression",
    )

    sub.add_parser(
        "audit",
        help="120-point evidence-backed repo inspection (security, API, architecture)",
    )

    run_p = sub.add_parser("run", help="run selected gates in order")
    run_p.add_argument("--only", default=None, help="comma-separated gates")
    run_p.add_argument("--skip", default=None, help="comma-separated gates")
    run_p.add_argument("--base", default=None)
    run_p.add_argument("--post-review", action="store_true")
    run_p.add_argument(
        "--changed", action="store_true", help="only files changed vs --base"
    )
    run_p.add_argument(
        "--plan", action="store_true", help="show selected execution without running it"
    )
    run_p.add_argument(
        "--time-budget-seconds",
        type=int,
        default=None,
        help="plan within this budget; only advisory checks may be deferred",
    )
    run_p.add_argument("--language", action="append", dest="languages")
    run_p.add_argument("--risk", choices=["off", "auto"], default="off")
    run_p.add_argument(
        "--full",
        action="store_true",
        help="on GitHub Actions, run the heavy suite even when ci.mode=local",
    )

    init = sub.add_parser(
        "init", help="write default sheriff.toml and a pinned The Code Sheriff workflow"
    )
    _add_onboard_args(init, require_check=False)
    setup = sub.add_parser(
        "setup",
        help="one command: defaults, workflow, hooks, required check, first baseline",
    )
    _add_onboard_args(setup, require_check=True, hooks=True, run=True, agents=True)
    setup.add_argument(
        "--app",
        action="store_true",
        help="also start GitHub App registration after writing files",
    )

    gh_app = sub.add_parser(
        "github-app",
        help="register The Code Sheriff GitHub App (runs on each repo's Actions minutes)",
    )
    gh_cmd = gh_app.add_subparsers(dest="app_command", required=True)
    manifest_p = gh_cmd.add_parser(
        "manifest", help="print the GitHub App manifest JSON"
    )
    manifest_p.add_argument("--name", default="The Code Sheriff")
    manifest_p.add_argument("--webhook-url", default="")
    manifest_p.add_argument("--redirect-url", default="")
    manifest_p.add_argument(
        "--public",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="list the App as public (default: true)",
    )
    register = gh_cmd.add_parser(
        "register", help="create the App via GitHub's manifest flow"
    )
    register.add_argument("--host", default="127.0.0.1")
    register.add_argument("--port", type=int, default=8787)
    register.add_argument("--webhook-url", default="")
    register.add_argument("--org", default="", help="create under this GitHub org")
    register.add_argument("--name", default="The Code Sheriff")
    register.add_argument(
        "--public",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="create a public App (default: true)",
    )
    register.add_argument(
        "--no-open",
        action="store_true",
        help="do not open a browser for create/install",
    )
    register.add_argument(
        "--no-init",
        action="store_true",
        help="do not write sheriff.toml / workflow after the App is created",
    )
    serve = gh_cmd.add_parser(
        "serve", help="receive GitHub webhooks and dispatch Actions"
    )
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8787)
    handle = gh_cmd.add_parser(
        "handle", help="process one webhook payload from a file or stdin"
    )
    handle.add_argument("payload", nargs="?", default="-")
    handle.add_argument("--event", default="pull_request")
    handle.add_argument("--signature", default="")
    gh_cmd.add_parser(
        "prepare", help="verify a repository_dispatch payload in GitHub Actions"
    )
    check = gh_cmd.add_parser("check", help="create a check run on GITHUB_REPOSITORY")
    check.add_argument("--name", default="The Code Sheriff")
    check.add_argument(
        "--status",
        choices=["queued", "in_progress", "completed"],
        default="in_progress",
    )
    check.add_argument("--conclusion", default="")
    check.add_argument("--title", default="")
    check.add_argument("--summary", default="")
    token_p = gh_cmd.add_parser("token", help="mint an installation access token")
    token_p.add_argument("--installation-id", required=True)
    hook = gh_cmd.add_parser("webhook", help="set the GitHub App webhook URL")
    hook.add_argument("--url", required=True)
    gh_cmd.add_parser("deliveries", help="show recent webhook delivery ids")
    gh_cmd.add_parser("install-url", help="print the public App install URL")

    baseline_p = sub.add_parser(
        "baseline",
        help="write .sheriff-baseline.json from the last run (grandfather current findings)",
    )
    baseline_p.add_argument(
        "--ratchet",
        action="store_true",
        help="merge with the existing baseline; raise coverage floor if it improved",
    )

    report_p = sub.add_parser(
        "report",
        help="reprint the last run: scorecard, performance, issues, recommendations",
    )
    report_p.add_argument(
        "--format",
        dest="report_format",
        choices=["console", "markdown", "html", "json", "sarif", "junit"],
        default="console",
        help="console (default), markdown, html, or json",
    )
    report_p.add_argument(
        "--diff",
        dest="report_diff",
        nargs="?",
        const="history",
        default=None,
        help="show only findings new since the previous history entry or a git ref",
    )
    watch_p = sub.add_parser("watch", help="rerun cheap gates when files change")
    watch_p.add_argument(
        "--interval", type=float, default=1.5, help="poll interval in seconds"
    )

    check_local = sub.add_parser(
        "check",
        help="local review of staged or changed files (same policies as the App)",
    )
    check_local.add_argument("--base", default=None)

    serve_p = sub.add_parser(
        "serve", help="local triage dashboard + JSON API over .quality-reports"
    )
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8788)

    ingest_p = sub.add_parser("ingest", help="merge an external SARIF report")
    ingest_p.add_argument("--sarif", required=True)

    evidence_p = sub.add_parser("evidence", help="export compliance evidence bundle")
    evidence_p.add_argument("action", choices=["export"])
    evidence_p.add_argument(
        "--framework",
        default="soc2",
        choices=["soc2", "iso27001", "hipaa"],
    )

    notes_p = sub.add_parser("notes", help="draft user-visible release notes")
    notes_p.add_argument("--from-merged", dest="from_merged", action="store_true")
    notes_p.add_argument("--title", action="append", dest="titles")

    fix_pr = sub.add_parser(
        "fix-pr", help="apply accepted patches on a new sheriff/fix/<pr> branch"
    )
    fix_pr.add_argument("--pr", required=True)
    fix_pr.add_argument("--create-branch", action="store_true")

    rules_p = sub.add_parser("rules", help="preview or simulate review rules")
    rules_cmd = rules_p.add_subparsers(dest="rules_command", required=True)
    preview = rules_cmd.add_parser("preview", help="count files a path glob would hit")
    preview.add_argument("--paths", default="**/*")
    sim = rules_cmd.add_parser("sim", help="estimate comment volume for a path glob")
    sim.add_argument("--paths", default="**/*")
    sim.add_argument("--base", default=None)

    reports_p = sub.add_parser(
        "reports", help="retain or garbage-collect local reports"
    )
    reports_p.add_argument("action", choices=["gc"])
    reports_p.add_argument("--days", type=int, default=None)

    cli_ext.register_parsers(sub)

    args = parser.parse_args(argv)
    root = project_root(args.root)
    os.chdir(root)
    config = load_config(root)
    if args.policy:
        config.policy = args.policy

    ext_result = cli_ext.dispatch(args, root, config)
    if ext_result is not None:
        return ext_result

    if args.command == "github-app":
        from quality_gates.github_app import cli_github_app

        return cli_github_app(args)
    if args.command == "policy":
        from quality_gates.product import verify_policy_bundle

        key = args.key or os.environ.get("QUALITY_POLICY_KEY", "")
        if not key:
            print("policy verify requires --key or QUALITY_POLICY_KEY", file=sys.stderr)
            return 2
        payload = verify_policy_bundle(args.bundle, key)
        print(json.dumps(payload, indent=2))
        return 0 if payload["valid"] else 1
    if args.command == "trace":
        from quality_gates.product import export_trace

        payload = export_trace(root)
        output = args.output or root / ".quality-reports" / "agent-trace.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(output)
        return 0
    if args.command == "redact":
        from quality_gates.product import redaction_preview

        source = args.input or root / ".quality-reports" / "quality-report.json"
        print(json.dumps(redaction_preview(source), indent=2))
        return 0
    if args.command == "risk":
        from quality_gates.product import risk_zones

        paths = _csv(args.paths) or [
            item.path for item in discover_changes(root).changes
        ]
        print(json.dumps(risk_zones(paths), indent=2))
        return 0
    if args.command == "sarif":
        from quality_gates.product import sarif_baseline

        payload = sarif_baseline(
            root, args.input if args.sarif_command == "import-baseline" else None
        )
        if args.sarif_command == "export-baseline":
            output = args.output or root / ".quality-reports" / "sarif-baseline.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(output)
        else:
            print(json.dumps(payload, indent=2))
        return 0
    if args.command == "fleet":
        from quality_gates.product import (
            fleet_metrics,
            fleet_summary,
            render_fleet_markdown,
        )

        if getattr(args, "fleet_command", "export") == "report":
            base = (args.scan or root.parent).expanduser()
            summary = fleet_summary(base)
            if args.format == "json":
                text = json.dumps(summary, indent=2) + "\n"
            else:
                text = render_fleet_markdown(summary)
            output = args.output
            if output is None:
                print(text, end="")
                return 0
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text, encoding="utf-8")
            print(output)
            return 0
        if not args.opt_in:
            print("fleet export requires explicit --opt-in", file=sys.stderr)
            return 2
        payload = fleet_metrics(root)
        output = args.output or root / ".quality-reports" / "fleet-metrics.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(output)
        return 0
    if args.command == "benchmark":
        from quality_gates.product import static_benchmark

        roots = args.benchmark_roots or [root]
        print(json.dumps(static_benchmark(roots, config), indent=2))
        return 0
    if args.command == "targets":
        from quality_gates.product import select_monorepo_targets

        paths = _csv(args.paths) or [
            item.path for item in discover_changes(root).changes
        ]
        print(json.dumps(select_monorepo_targets(root, paths), indent=2))
        return 0
    if args.command in {"init", "setup"}:
        return _onboard(root, args)
    if args.command == "mcp":
        from quality_gates.mcp_server import serve

        return serve()
    if args.command == "oracle":
        return _oracle(root, args)
    if args.command == "fix":
        return _fix(root, apply_patches=not args.no_patches, as_json=args.json)
    if args.command == "certify":
        return _certify(
            root,
            as_json=args.json,
            sign=bool(getattr(args, "sign", False)),
            verify=bool(getattr(args, "verify", False)),
            key=getattr(args, "key", None),
        )
    if args.command == "apply":
        return _apply_one(root, args.finding_id, as_json=args.json)
    if args.command == "eval":
        return _eval(root, args)
    if args.command == "baseline":
        return _baseline(root, config, ratchet=args.ratchet)
    if args.command == "report":
        return _print_report(
            root,
            fmt=args.report_format,
            as_json=args.json,
            diff=getattr(args, "report_diff", None),
        )
    if args.command == "watch":
        return _watch(root, config, interval=args.interval)
    if args.command == "serve":
        from quality_gates.platform import serve_api

        return serve_api(root, host=args.host, port=args.port)
    if args.command == "ingest":
        from quality_gates.platform import ingest_sarif

        findings = ingest_sarif(root, args.sarif)
        print(json.dumps([item.to_dict() for item in findings], indent=2))
        return 0
    if args.command == "evidence":
        from quality_gates.platform import export_evidence

        path = export_evidence(root, framework=args.framework)
        print(path)
        return 0
    if args.command == "notes":
        from quality_gates.notes import draft_notes

        pulls = [{"title": title} for title in (args.titles or [])]
        print("\n".join(draft_notes(pulls)) or "(no user-visible notes)")
        return 0
    if args.command == "fix-pr":
        from quality_gates.fix_pr import apply_fix_pr
        from quality_gates.models import Finding

        report = root / ".quality-reports" / "review.json"
        findings: list[Finding] = []
        if report.is_file():
            payload = json.loads(report.read_text(encoding="utf-8"))
            for item in payload.get("findings") or []:
                findings.append(
                    Finding(
                        gate="review",
                        message=str(item.get("message") or ""),
                        rule=item.get("rule"),
                        path=item.get("path"),
                        patch=item.get("patch"),
                    )
                )
        print(
            json.dumps(
                apply_fix_pr(
                    root,
                    findings,
                    pr=args.pr,
                    create_branch=args.create_branch,
                ),
                indent=2,
            )
        )
        return 0
    if args.command == "rules":
        from quality_gates.detect import iter_project_files
        from quality_gates.platform import simulate_rule

        paths = [
            path.relative_to(root).as_posix()
            for path in iter_project_files(root, config)
        ]
        print(json.dumps(simulate_rule(paths, args.paths), indent=2))
        return 0
    if args.command == "reports":
        from quality_gates.review.cost import gc_reports

        days = args.days if args.days is not None else config.retention_days
        print(json.dumps(gc_reports(root, days=days), indent=2))
        return 0
    if args.command == "check":
        result = gate_runners.run_review(
            root,
            config,
            _resolve_languages(root, config, None, None),
            base=args.base,
            post=False,
        )
        return _emit([result], root, config, args.json, ["review"])
    if args.command == "doctor":
        return doctor(root, config, install=args.install, as_json=args.json)
    if args.command == "cache":
        if args.provenance and args.action == "status":
            from quality_gates.product import cache_provenance

            payload = cache_provenance(
                cache_dir() / "results-v1", offline=config.offline
            )
        else:
            payload = clean_cache() if args.action == "clean" else cache_status()
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            verb = "removed" if args.action == "clean" else "contains"
            print(
                f"cache {payload['path']} {verb} {payload['entries']} entries "
                f"({payload['bytes']} bytes)"
            )
        return 0
    if args.command == "detect":
        info = detect_languages(root, config)
        return _print_detect(info, args.json)

    if args.command == "bump":
        try:
            new, written = apply_bump(root, config, args.part)
        except ValueError as exc:
            print(f"bump failed: {exc}", file=sys.stderr)
            return 1
        print(f"bumped to {new}")
        for path in written:
            print(f"  {path.relative_to(root)}")
        return 0

    if args.command == "ignore":
        from quality_gates.ignore import append_ignore

        path = append_ignore(
            root,
            rule=args.rule,
            path=args.path,
            gate=args.gate,
            reason=args.reason,
            owner=args.owner,
            days=args.days,
        )
        print(f"wrote {path.relative_to(root)}")
        return 0
    if args.command == "timing":
        from quality_gates.timing import accept_timings

        if not args.tests and not args.all_regressed:
            print("pass --test NODEID or --all-regressed", file=sys.stderr)
            return 2
        payload = accept_timings(
            root, nodeids=args.tests, all_regressed=args.all_regressed
        )
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            accepted = payload.get("accepted") or []
            print(f"accepted {len(accepted)} timing baseline(s)")
            for item in accepted:
                print(f"  {item}")
        return 0 if payload.get("accepted") else 1

    languages = _resolve_languages(root, config, getattr(args, "languages", None), None)
    if args.command == "format":
        result = gate_runners.run_format(root, config, languages, check=not args.write)
        return _emit([result], root, config, args.json, ["format"])
    if args.command == "lint":
        result = gate_runners.run_lint(root, config, languages)
        return _emit([result], root, config, args.json, ["lint"])
    if args.command == "regex":
        result = gate_runners.run_regex(root, config, base=args.base)
        return _emit([result], root, config, args.json, ["regex"])
    if args.command == "packages":
        result = gate_runners.run_packages(root, config, languages, base=args.base)
        return _emit([result], root, config, args.json, ["packages"])
    if args.command == "dry":
        result = gate_runners.run_dry(root, config, languages)
        return _emit([result], root, config, args.json, ["dry"])
    if args.command == "dead":
        result = gate_runners.run_dead(root, config, languages)
        return _emit([result], root, config, args.json, ["dead"])
    if args.command == "sbom":
        from quality_gates.sbom import write_sbom

        payload = write_sbom(root, fmt=args.sbom_format)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            files = payload.get("files") or {}
            if files:
                print("wrote " + ", ".join(files.values()))
            for note in payload.get("notes") or []:
                print(note)
            print(f"components: {payload.get('components', 0)}")
        return 0
    if args.command == "security":
        result = gate_runners.run_security(root, config, languages)
        return _emit([result], root, config, args.json, ["security"])
    if args.command == "compile":
        security = None
        if not args.force and config.compile_require_security:
            security = gate_runners.run_security(root, config, languages)
            results = [security]
            compile_result = gate_runners.run_compile(
                root, config, languages, security=security
            )
            results.append(compile_result)
            return _emit(results, root, config, args.json, ["security", "compile"])
        from quality_gates.models import GateResult as GR

        fake = GR(
            name="security", status="pass", notes=["--force or require_security=false"]
        )
        result = gate_runners.run_compile(root, config, languages, security=fake)
        return _emit([result], root, config, args.json, ["compile"])
    if args.command == "version":
        result = gate_runners.run_version(root, config, base=args.base)
        return _emit([result], root, config, args.json, ["version"])
    if args.command == "review":
        result = gate_runners.run_review(
            root, config, languages, base=args.base, post=args.post
        )
        return _emit([result], root, config, args.json, ["review"])
    if args.command == "ui":
        result = gate_runners.run_ui(
            root,
            config,
            base=args.base,
            force_all=args.all,
            list_only=args.list,
        )
        return _emit([result], root, config, args.json, ["ui"])
    if args.command == "impact":
        result = gate_runners.run_impact(root, config, base=args.base)
        return _emit([result], root, config, args.json, ["impact"])
    if args.command == "merge":
        result = gate_runners.run_merge(
            root,
            config,
            base=args.base,
            verify=args.verify,
            siblings=args.siblings,
        )
        return _emit([result], root, config, args.json, ["merge"])
    if args.command == "comments":
        result = gate_runners.run_comments(
            root, config, fail=True if args.fail else None
        )
        required = ["comments"] if args.fail else []
        return _emit([result], root, config, args.json, required)
    if args.command == "coverage":
        result = gate_runners.run_coverage(root, config)
        return _emit([result], root, config, args.json, ["coverage"])
    if args.command == "test":
        result = gate_runners.run_tests(root, config)
        return _emit([result], root, config, args.json, ["test"])
    if args.command == "audit":
        result = gate_runners.run_audit(root, config)
        return _emit([result], root, config, args.json, ["audit"])
    if args.command == "run":
        only = _csv(args.only) or None
        skip = _csv(args.skip)
        bad = unknown_gates(only) + unknown_gates(skip)
        if bad:
            print(
                "unknown gate(s): "
                + ", ".join(dict.fromkeys(bad))
                + ". Choose from: "
                + ", ".join(GATES),
                file=sys.stderr,
            )
            return 2
        gates = select_gates(
            config,
            only=only,
            skip=skip,
            full=args.full,
        )
        if not args.only and not args.full:
            print(f"ci.mode={config.ci_mode} · gates: {', '.join(gates)}")
        manifest = (
            discover_changes(root, args.base)
            if args.changed or getattr(args, "risk", "off") == "auto"
            else None
        )
        if manifest is not None and manifest.state == "unknown":
            print(f"change discovery failed: {manifest.reason}", file=sys.stderr)
            return 2
        if manifest is not None:
            manifest.write(root)
            gates = select_change_gates(gates, manifest.paths)
            gates, risk_notes = risk_decision(
                gates,
                manifest.paths,
                required=config.fail_on,
                mode=getattr(args, "risk", "off"),
            )
            for note in risk_notes:
                print(note)
        changed = (
            [
                (root / path).resolve()
                for path in manifest.paths
                if (root / path).is_file()
            ]
            if manifest is not None
            else None
        )
        plan = build_plan(
            gates,
            config,
            manifest,
            root=root,
            time_budget_seconds=args.time_budget_seconds,
        )
        write_plan(root, plan)
        if args.plan:
            if args.json:
                print(json.dumps({"plan": [item.to_dict() for item in plan]}, indent=2))
            else:
                print(render_plan(plan))
            return 0
        gates = [item.name for item in plan if item.status == "selected"]
        languages = _resolve_languages(root, config, args.languages, changed)
        results = []
        prior = []
        for gate in gates:
            started = time.perf_counter()
            if gate == "format":
                item = gate_runners.run_format(
                    root, config, languages, check=True, scope=changed
                )
            elif gate == "lint":
                item = gate_runners.run_lint(root, config, languages, scope=changed)
            elif gate == "regex":
                item = gate_runners.run_regex(
                    root,
                    config,
                    base=args.base,
                    diff=manifest.diff if manifest else None,
                )
            elif gate == "packages":
                item = gate_runners.run_packages(
                    root,
                    config,
                    languages,
                    base=args.base,
                    diff=manifest.diff if manifest else None,
                )
            elif gate == "dry":
                item = gate_runners.run_dry(root, config, languages)
            elif gate == "dead":
                item = gate_runners.run_dead(root, config, languages)
            elif gate == "security":
                item = gate_runners.run_security(root, config, languages)
            elif gate == "compile":
                security = next((row for row in prior if row.name == "security"), None)
                if (
                    security is None
                    and config.compile_require_security
                    and "security" not in gates
                ):
                    security = gate_runners.run_security(root, config, languages)
                    security.duration_ms = max(
                        0, int((time.perf_counter() - started) * 1000)
                    )
                    results.append(security)
                    prior.append(security)
                    started = time.perf_counter()
                if not config.compile_require_security and security is None:
                    from quality_gates.models import GateResult as GR

                    security = GR(name="security", status="pass")
                item = gate_runners.run_compile(
                    root, config, languages, security=security
                )
            elif gate == "contract":
                item = gate_runners.run_contract(root, config, base=args.base)
            elif gate == "version":
                item = gate_runners.run_version(
                    root, config, base=args.base, manifest=manifest
                )
            elif gate == "impact":
                item = gate_runners.run_impact(root, config, base=args.base)
            elif gate == "merge":
                item = gate_runners.run_merge(root, config, base=args.base)
            elif gate == "test":
                item = gate_runners.run_tests(
                    root, config, selection=manifest.paths if manifest else None
                )
            elif gate == "coverage":
                item = gate_runners.run_coverage(
                    root,
                    config,
                    manifest=manifest,
                    selection=manifest.paths if manifest else None,
                )
            elif gate == "audit":
                item = gate_runners.run_audit(root, config)
            elif gate == "ui":
                compile_prior = next(
                    (row for row in prior if row.name == "compile"), None
                )
                item = gate_runners.run_ui(
                    root,
                    config,
                    base=args.base,
                    compile_result=compile_prior,
                    manifest=manifest,
                )
            elif gate == "review":
                post = args.post_review or (
                    is_pr_event() and config.ai_review != "never"
                )
                item = gate_runners.run_review(
                    root,
                    config,
                    languages,
                    base=args.base,
                    post=post,
                    prior=prior,
                    manifest=manifest,
                )
            elif gate == "comments":
                item = gate_runners.run_comments(root, config)
            elif gate in {
                "migration",
                "authorization",
                "resilience",
                "mutation",
                "performance",
            }:
                item = gate_runners.run_advanced(
                    root, config, gate, manifest.paths if manifest else []
                )
            else:
                continue
            item.duration_ms = max(0, int((time.perf_counter() - started) * 1000))
            plan_item = next((entry for entry in plan if entry.name == gate), None)
            selection = list(plan_item.inputs) if plan_item else []
            attach_evidence(item, root, config, manifest=manifest, selection=selection)
            results.append(item)
            prior.append(item)
        return _emit(
            results,
            root,
            config,
            args.json,
            [item.name for item in plan if item.required],
        )
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
