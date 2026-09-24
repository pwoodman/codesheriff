"""Benchmark framework: validate against real open-source repos with known issues.

Supports Sentry, Grafana, Keycloak, and custom repos. Measures bug catch rate,
false positive rate, cross-file detection, and time-to-first-review.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quality_gates.metrics import ReviewMetrics, compute_metrics

VALIDATION_REPOS = {
    "sentry": {
        "url": "https://github.com/getsentry/sentry",
        "description": "Error tracking platform (Python + TypeScript)",
        "primary_languages": ["python", "typescript"],
        "size_estimate": "~80k LOC",
        "known_issues": [
            "CVEs in older dependencies",
            "Auth bypass patterns",
            "SQL injection risks in query builders",
        ],
    },
    "grafana": {
        "url": "https://github.com/grafana/grafana",
        "description": "Observability platform (Go + TypeScript)",
        "primary_languages": ["go", "typescript"],
        "size_estimate": "~70k LOC",
        "known_issues": [
            "Auth/permission bugs",
            "XSS in dashboard rendering",
            "SQL injection in query builders",
        ],
    },
    "keycloak": {
        "url": "https://github.com/keycloak/keycloak",
        "description": "Identity and access management (Java + TypeScript)",
        "primary_languages": ["java", "typescript"],
        "size_estimate": "~60k LOC",
        "known_issues": [
            "IDOR vulnerabilities",
            "Session fixation patterns",
            "Token validation gaps",
        ],
    },
}

# Open-source benchmark suites we score against (not scanned with gates; they
# provide ground-truth PRs/golden comments). Run via:
#   codesheriff eval --suite martian      # withmartian CRB golden comments
#   codesheriff eval --suite aacrbench    # Alibaba AACR-Bench schema
EXTERNAL_SUITES = {
    "withmartian-code-review-benchmark": {
        "url": "https://github.com/withmartian/code-review-benchmark",
        "license": "MIT",
        "kind": "golden-comments",
        "prs": 50,
        "repos": ("sentry", "grafana", "cal", "discourse", "keycloak"),
        "compares": ("Macroscope", "Bugbot", "Greptile", "Sourcery"),
        "command": "codesheriff eval --suite martian --download",
        "adapter": "quality_gates.review.external_eval",
    },
    "aacr-bench": {
        "url": "https://github.com/alibaba/aacr-bench",
        "license": "Apache-2.0",
        "kind": "pr-diff-benchmark",
        "prs": 200,
        "repos": 50,
        "languages": 10,
        "command": "codesheriff eval --suite aacrbench",
        "adapter": "quality_gates.review.aacr_bench",
    },
}


def register_external_suite(name: str, **info: Any) -> None:
    """Register an additional open-source benchmark suite."""
    EXTERNAL_SUITES[name] = dict(info)


@dataclass
class BenchmarkCase:
    """A single benchmark case: a repo + what to look for."""

    repo_name: str
    repo_url: str
    description: str
    expected_bugs: list[str]
    languages: list[str]
    scan_paths: list[str] = field(default_factory=list)
    skip_gates: list[str] = field(default_factory=list)
    time_budget_seconds: int = 300


@dataclass
class BenchmarkResult:
    """Result of running a benchmark case."""

    case: BenchmarkCase
    metrics: ReviewMetrics
    findings_matched: int = 0
    findings_unmatched: int = 0
    false_positives: int = 0
    true_positives: int = 0
    missed_bugs: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    success: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": self.case.repo_name,
            "description": self.case.description,
            "success": self.success,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
            "findings_count": self.metrics.findings_count,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "missed_bugs": self.missed_bugs,
            "metrics": self.metrics.to_dict(),
        }


def clone_repo(url: str, dest: Path, depth: int = 1) -> bool:
    """Shallow clone a repo for benchmarking."""
    if dest.exists():
        return True
    try:
        subprocess.run(
            ["git", "clone", "--depth", str(depth), url, str(dest)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def run_benchmark(
    case: BenchmarkCase,
    root: Path,
    *,
    skip_gates: list[str] | None = None,
) -> BenchmarkResult:
    """Run a single benchmark case against a repo."""
    start = time.monotonic()
    dest = root / "benchmarks" / case.repo_name

    if not clone_repo(case.repo_url, dest):
        return BenchmarkResult(
            case=case,
            metrics=ReviewMetrics(),
            success=False,
            error=f"Failed to clone {case.repo_url}",
        )

    skip = list(case.skip_gates) + list(skip_gates or [])
    skip_str = ",".join(skip) if skip else ""

    try:
        cmd = [
            "codesheriff",
            "--root",
            str(dest),
            "run",
            "--skip",
            skip_str,
            "--json",
            "--policy",
            "observe",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=case.time_budget_seconds,
            cwd=str(dest),
        )
        duration = time.monotonic() - start

        if result.returncode not in (0, 2):
            return BenchmarkResult(
                case=case,
                metrics=ReviewMetrics(),
                success=False,
                error=f"Exit code {result.returncode}: {result.stderr[:500]}",
                duration_seconds=duration,
            )

        try:
            report = json.loads(result.stdout)
        except json.JSONDecodeError:
            report = {}

        findings = report.get("findings", [])
        from quality_gates.models import Finding

        parsed = []
        for f in findings:
            if isinstance(f, dict):
                parsed.append(
                    Finding(
                        gate=f.get("gate", "unknown"),
                        message=f.get("message", ""),
                        severity=f.get("severity", "warning"),
                        path=f.get("path"),
                        line=f.get("line"),
                        rule=f.get("rule"),
                    )
                )

        metrics = compute_metrics(
            parsed,
            duration_ms=int(duration * 1000),
            files_scanned=report.get("files_scanned", 0),
            platform="benchmark",
            languages=case.languages,
        )

        matched = sum(
            1
            for expected in case.expected_bugs
            if any(
                expected.lower() in f.message.lower()
                or expected.lower() in (f.rule or "").lower()
                for f in parsed
            )
        )

        return BenchmarkResult(
            case=case,
            metrics=metrics,
            findings_matched=matched,
            findings_unmatched=len(parsed) - matched,
            true_positives=matched,
            false_positives=max(0, len(parsed) - matched),
            missed_bugs=[
                b
                for b in case.expected_bugs
                if b
                not in [
                    e
                    for e in case.expected_bugs
                    if any(
                        e.lower() in f.message.lower()
                        or e.lower() in (f.rule or "").lower()
                        for f in parsed
                    )
                ]
            ],
            duration_seconds=duration,
        )
    except subprocess.TimeoutExpired:
        return BenchmarkResult(
            case=case,
            metrics=ReviewMetrics(),
            success=False,
            error=f"Timed out after {case.time_budget_seconds}s",
            duration_seconds=time.monotonic() - start,
        )
    except Exception as exc:
        return BenchmarkResult(
            case=case,
            metrics=ReviewMetrics(),
            success=False,
            error=str(exc),
            duration_seconds=time.monotonic() - start,
        )


def run_full_benchmark(root: Path) -> dict[str, Any]:
    """Run all validation repo benchmarks and return a scorecard."""
    results: list[BenchmarkResult] = []
    total_start = time.monotonic()

    for name, info in VALIDATION_REPOS.items():
        case = BenchmarkCase(
            repo_name=name,
            repo_url=info["url"],
            description=info["description"],
            expected_bugs=info["known_issues"],
            languages=info["primary_languages"],
            skip_gates=["compile", "test", "coverage", "ui"],
        )
        result = run_benchmark(case, root)
        results.append(result)

    total_duration = time.monotonic() - total_start
    total_findings = sum(r.metrics.findings_count for r in results)
    total_tp = sum(r.true_positives for r in results)
    total_fp = sum(r.false_positives for r in results)
    successful = [r for r in results if r.success]

    scorecard = {
        "suite": "validation-benchmark",
        "repos_evaluated": len(results),
        "repos_successful": len(successful),
        "total_findings": total_findings,
        "total_true_positives": total_tp,
        "total_false_positives": total_fp,
        "precision": round(total_tp / max(1, total_tp + total_fp), 4),
        "total_duration_seconds": round(total_duration, 2),
        "external_suites": EXTERNAL_SUITES,
        "results": [r.to_dict() for r in results],
    }

    dest = root / ".quality-reports" / "eval"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "VALIDATION_BENCHMARK.json").write_text(
        json.dumps(scorecard, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "VALIDATION_BENCHMARK.md").write_text(
        _render_benchmark_scorecard(scorecard), encoding="utf-8"
    )
    return scorecard


def _render_benchmark_scorecard(scorecard: dict[str, Any]) -> str:
    lines = [
        "# Validation Benchmark Scorecard",
        "",
        f"- Repos evaluated: {scorecard['repos_evaluated']}",
        f"- Repos successful: {scorecard['repos_successful']}",
        f"- Total findings: {scorecard['total_findings']}",
        f"- True positives: {scorecard['total_true_positives']}",
        f"- False positives: {scorecard['total_false_positives']}",
        f"- Precision: {scorecard['precision']:.2%}",
        f"- Total duration: {scorecard['total_duration_seconds']:.1f}s",
        "",
        "## Per-Repo Results",
        "",
        "| Repo | Findings | TP | FP | Duration | Status |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for result in scorecard["results"]:
        status = "OK" if result["success"] else f"FAIL: {result['error'][:40]}"
        lines.append(
            f"| {result['repo']} | {result['findings_count']} | "
            f"{result['true_positives']} | {result['false_positives']} | "
            f"{result['duration_seconds']:.1f}s | {status} |"
        )
    lines.append("")
    return "\n".join(lines)


def register_custom_repo(
    name: str,
    url: str,
    description: str,
    languages: list[str],
    expected_issues: list[str] | None = None,
) -> None:
    """Register a custom repo for benchmarking."""
    VALIDATION_REPOS[name] = {
        "url": url,
        "description": description,
        "primary_languages": languages,
        "known_issues": expected_issues or [],
        "size_estimate": "custom",
    }
