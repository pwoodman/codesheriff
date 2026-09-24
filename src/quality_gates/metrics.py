"""Competitive metrics: the numbers that decide whether a review bot is tolerable.

Publishes metrics competitors don't: re-triage rate, termination, confidence
calibration, token efficiency, and cross-file detection rate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quality_gates.models import Finding


@dataclass
class ReviewMetrics:
    """Aggregated metrics from a review run."""

    timestamp: str = ""
    duration_ms: int = 0
    findings_count: int = 0
    findings_by_severity: dict[str, int] = field(default_factory=dict)
    findings_by_gate: dict[str, int] = field(default_factory=dict)
    confidence_scores: list[float] = field(default_factory=list)
    mean_confidence: float = 0.0
    median_confidence: float = 0.0
    tokens_consumed: int = 0
    files_scanned: int = 0
    lines_scanned: int = 0
    cross_file_violations: int = 0
    cross_file_detection_rate: float = 0.0
    retriage_rate: float = 0.0
    termination_iterations: int = 0
    terminated: bool = False
    closed_loop_resolution_rate: float = 0.0
    suppression_durability: float = 0.0
    false_positive_estimate: float = 0.0
    setup_time_seconds: float = 0.0
    time_to_first_review_seconds: float = 0.0
    platform: str = "cli"
    languages: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None and v != ""}

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


def compute_metrics(
    findings: list[Finding],
    *,
    duration_ms: int = 0,
    tokens_consumed: int = 0,
    files_scanned: int = 0,
    lines_scanned: int = 0,
    cross_file_violations: int = 0,
    cross_file_total: int = 0,
    retriage_rate: float = 0.0,
    termination_iterations: int = 0,
    terminated: bool = False,
    closed_loop_resolution_rate: float = 0.0,
    suppression_durability: float = 0.0,
    false_positive_estimate: float = 0.0,
    setup_time_seconds: float = 0.0,
    time_to_first_review_seconds: float = 0.0,
    platform: str = "cli",
    languages: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> ReviewMetrics:
    """Compute ReviewMetrics from a list of findings."""
    import datetime

    by_severity: dict[str, int] = {}
    by_gate: dict[str, int] = {}
    confidences: list[float] = []

    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_gate[f.gate] = by_gate.get(f.gate, 0) + 1
        confidences.append(f.confidence)

    mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
    sorted_conf = sorted(confidences)
    if sorted_conf:
        mid = len(sorted_conf) // 2
        median_conf = (
            sorted_conf[mid]
            if len(sorted_conf) % 2
            else (sorted_conf[mid - 1] + sorted_conf[mid]) / 2
        )
    else:
        median_conf = 0.0

    detection_rate = (
        cross_file_violations / cross_file_total if cross_file_total > 0 else 0.0
    )

    return ReviewMetrics(
        timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
        duration_ms=duration_ms,
        findings_count=len(findings),
        findings_by_severity=by_severity,
        findings_by_gate=by_gate,
        confidence_scores=confidences[:100],
        mean_confidence=round(mean_conf, 4),
        median_confidence=round(median_conf, 4),
        tokens_consumed=tokens_consumed,
        files_scanned=files_scanned,
        lines_scanned=lines_scanned,
        cross_file_violations=cross_file_violations,
        cross_file_detection_rate=round(detection_rate, 4),
        retriage_rate=retriage_rate,
        termination_iterations=termination_iterations,
        terminated=terminated,
        closed_loop_resolution_rate=closed_loop_resolution_rate,
        suppression_durability=suppression_durability,
        false_positive_estimate=false_positive_estimate,
        setup_time_seconds=setup_time_seconds,
        time_to_first_review_seconds=time_to_first_review_seconds,
        platform=platform,
        languages=languages or [],
        extra=extra or {},
    )


def write_metrics(root: Path, metrics: ReviewMetrics) -> Path:
    """Write metrics to .quality-reports/metrics.json."""
    dest = root / ".quality-reports"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "metrics.json"
    path.write_text(metrics.to_json() + "\n", encoding="utf-8")
    return path


def load_metrics(root: Path) -> ReviewMetrics | None:
    """Load previously written metrics."""
    path = root / ".quality-reports" / "metrics.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return ReviewMetrics(
        **{k: v for k, v in data.items() if k in ReviewMetrics.__dataclass_fields__}
    )


def compare_metrics(ours: ReviewMetrics, theirs: dict[str, Any]) -> dict[str, Any]:
    """Compare our metrics against a competitor's published numbers."""
    comparison: dict[str, Any] = {
        "our_metrics": ours.to_dict(),
        "competitor": theirs,
        "advantages": [],
        "disadvantages": [],
    }

    their_recall = theirs.get("recall", 0)
    our_recall = 1.0 - ours.false_positive_estimate
    if our_recall > their_recall:
        comparison["advantages"].append(
            f"higher recall ({our_recall:.2%} vs {their_recall:.2%})"
        )
    elif our_recall < their_recall:
        comparison["disadvantages"].append(
            f"lower recall ({our_recall:.2%} vs {their_recall:.2%})"
        )

    their_fp = theirs.get("false_positive_rate", 0)
    if ours.false_positive_estimate < their_fp:
        comparison["advantages"].append(
            f"fewer false positives ({ours.false_positive_estimate:.2%} vs {their_fp:.2%})"
        )

    their_tokens = theirs.get("tokens_per_review", 0)
    if their_tokens > 0 and ours.tokens_consumed > 0:
        ratio = ours.tokens_consumed / their_tokens
        if ratio < 1:
            comparison["advantages"].append(f"token efficiency ({ratio:.2f}x)")
        else:
            comparison["disadvantages"].append(f"token usage ({ratio:.2f}x)")

    their_retriage = theirs.get("retriage_rate", 0)
    if ours.retriage_rate < their_retriage:
        comparison["advantages"].append(
            f"lower re-triage ({ours.retriage_rate:.2%} vs {their_retriage:.2%})"
        )

    return comparison


def render_metrics_summary(metrics: ReviewMetrics) -> str:
    """Render a human-readable metrics summary."""
    lines = [
        "# Review Metrics",
        "",
        f"- **Timestamp**: {metrics.timestamp}",
        f"- **Duration**: {metrics.duration_ms}ms",
        f"- **Platform**: {metrics.platform}",
        f"- **Languages**: {', '.join(metrics.languages) or 'unknown'}",
        "",
        "## Findings",
        f"- Total: {metrics.findings_count}",
    ]
    if metrics.findings_by_severity:
        lines.append(
            "- By severity: "
            + ", ".join(
                f"{k}={v}" for k, v in sorted(metrics.findings_by_severity.items())
            )
        )
    if metrics.findings_by_gate:
        lines.append(
            "- By gate: "
            + ", ".join(f"{k}={v}" for k, v in sorted(metrics.findings_by_gate.items()))
        )
    lines.extend(
        [
            "",
            "## Quality Signals",
            f"- Mean confidence: {metrics.mean_confidence:.2f}",
            f"- Median confidence: {metrics.median_confidence:.2f}",
            f"- Cross-file detection rate: {metrics.cross_file_detection_rate:.2%}",
            f"- Re-triage rate: {metrics.retriage_rate:.2%}",
            f"- False positive estimate: {metrics.false_positive_estimate:.2%}",
            f"- Closed-loop resolution: {metrics.closed_loop_resolution_rate:.2%}",
            f"- Suppression durability: {metrics.suppression_durability:.2%}",
            "",
            "## Performance",
            f"- Files scanned: {metrics.files_scanned}",
            f"- Lines scanned: {metrics.lines_scanned}",
            f"- Tokens consumed: {metrics.tokens_consumed}",
            f"- Setup time: {metrics.setup_time_seconds:.1f}s",
            f"- Time to first review: {metrics.time_to_first_review_seconds:.1f}s",
            f"- Termination: {'converged' if not metrics.terminated else 'stalled at ' + str(metrics.termination_iterations)}",
        ],
    )
    if metrics.extra:
        lines.extend(["", "## Extra"])
        for key, value in metrics.extra.items():
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)
