"""Tests for competitive metrics and benchmark framework."""

from __future__ import annotations

from pathlib import Path

from quality_gates.benchmark import (
    VALIDATION_REPOS,
    BenchmarkCase,
    BenchmarkResult,
    register_custom_repo,
)
from quality_gates.metrics import (
    ReviewMetrics,
    compare_metrics,
    compute_metrics,
    load_metrics,
    render_metrics_summary,
    write_metrics,
)
from quality_gates.models import Finding


def test_compute_metrics_basic() -> None:
    findings = [
        Finding(
            gate="review",
            message="eval() on untrusted input",
            severity="error",
            path="src/app.py",
            line=10,
            rule="unsafe-api",
            confidence=0.9,
        ),
        Finding(
            gate="lint",
            message="unused import",
            severity="warning",
            path="src/utils.py",
            line=5,
            rule="unused-import",
            confidence=0.7,
        ),
        Finding(
            gate="security",
            message="hardcoded secret",
            severity="error",
            path="src/config.py",
            line=20,
            rule="secret",
            confidence=0.95,
        ),
    ]
    metrics = compute_metrics(
        findings,
        duration_ms=1500,
        tokens_consumed=5000,
        files_scanned=10,
        lines_scanned=500,
        platform="cli",
        languages=["python"],
    )
    assert metrics.findings_count == 3
    assert metrics.findings_by_severity == {"error": 2, "warning": 1}
    assert metrics.findings_by_gate == {"review": 1, "lint": 1, "security": 1}
    assert metrics.mean_confidence > 0.8
    assert metrics.tokens_consumed == 5000
    assert metrics.files_scanned == 10
    assert metrics.platform == "cli"
    assert metrics.languages == ["python"]


def test_compute_metrics_empty() -> None:
    metrics = compute_metrics([], duration_ms=100)
    assert metrics.findings_count == 0
    assert metrics.mean_confidence == 0.0
    assert metrics.median_confidence == 0.0


def test_metrics_to_dict_roundtrip() -> None:
    metrics = compute_metrics(
        [Finding(gate="review", message="test", severity="error")],
        duration_ms=100,
    )
    d = metrics.to_dict()
    assert d["findings_count"] == 1
    assert d["duration_ms"] == 100
    restored = ReviewMetrics(
        **{k: v for k, v in d.items() if k in ReviewMetrics.__dataclass_fields__}
    )
    assert restored.findings_count == 1


def test_write_and_load_metrics(tmp_path: Path) -> None:
    metrics = compute_metrics(
        [Finding(gate="review", message="test", severity="error")],
        duration_ms=200,
    )
    path = write_metrics(tmp_path, metrics)
    assert path.exists()
    loaded = load_metrics(tmp_path)
    assert loaded is not None
    assert loaded.findings_count == 1
    assert loaded.duration_ms == 200


def test_load_metrics_missing(tmp_path: Path) -> None:
    assert load_metrics(tmp_path) is None


def test_render_metrics_summary() -> None:
    metrics = compute_metrics(
        [
            Finding(gate="review", message="a", severity="error", confidence=0.9),
            Finding(gate="lint", message="b", severity="warning", confidence=0.6),
        ],
        duration_ms=500,
        tokens_consumed=10000,
        files_scanned=20,
        retriage_rate=0.05,
        cross_file_violations=3,
        cross_file_total=10,
    )
    summary = render_metrics_summary(metrics)
    assert "Review Metrics" in summary
    assert "findings" in summary.lower()
    assert "5.00%" in summary


def test_compare_metrics() -> None:
    ours = compute_metrics(
        [Finding(gate="review", message="test", severity="error")],
        false_positive_estimate=0.05,
        tokens_consumed=5000,
        retriage_rate=0.02,
    )
    theirs = {
        "recall": 0.8,
        "false_positive_rate": 0.1,
        "tokens_per_review": 10000,
        "retriage_rate": 0.15,
    }
    comparison = compare_metrics(ours, theirs)
    assert "advantages" in comparison
    assert len(comparison["advantages"]) > 0


def test_validation_repos_defined() -> None:
    assert "sentry" in VALIDATION_REPOS
    assert "grafana" in VALIDATION_REPOS
    assert "keycloak" in VALIDATION_REPOS
    for _name, info in VALIDATION_REPOS.items():
        assert "url" in info
        assert "primary_languages" in info
        assert "known_issues" in info


def test_register_custom_repo() -> None:
    register_custom_repo(
        "my-repo",
        "https://github.com/example/repo",
        "Test repo",
        ["python"],
        expected_issues=["bug1", "bug2"],
    )
    assert "my-repo" in VALIDATION_REPOS
    assert VALIDATION_REPOS["my-repo"]["primary_languages"] == ["python"]
    del VALIDATION_REPOS["my-repo"]


def test_benchmark_case_dataclass() -> None:
    case = BenchmarkCase(
        repo_name="test",
        repo_url="https://github.com/test/repo",
        description="Test",
        expected_bugs=["bug1"],
        languages=["python"],
    )
    assert case.repo_name == "test"
    assert case.time_budget_seconds == 300


def test_benchmark_result_dataclass() -> None:
    case = BenchmarkCase(
        repo_name="test",
        repo_url="https://github.com/test/repo",
        description="Test",
        expected_bugs=[],
        languages=["python"],
    )
    result = BenchmarkResult(
        case=case,
        metrics=ReviewMetrics(findings_count=5),
        true_positives=3,
        false_positives=2,
    )
    d = result.to_dict()
    assert d["repo"] == "test"
    assert d["true_positives"] == 3


def test_competitive_metrics_in_scorecard() -> None:
    from quality_gates.review.evalbench import _competitive_metrics

    payload = {
        "recall": 0.9,
        "mean_precision": 0.85,
        "retriage": {"retriage_rate": 0.03},
        "termination": {"iterations_to_stall": 5, "stalled": False},
    }
    competitive = _competitive_metrics(payload)
    assert "retriage_rate" in competitive
    assert "termination" in competitive
    assert "cross_file_rate" in competitive
    assert competitive["retriage_rate"] == "3.00%"
    assert competitive["termination"] == "converges"
