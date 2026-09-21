"""P0 track: confidence filter, strictness mapping, walkthrough, pause/resume."""

from __future__ import annotations

from pathlib import Path

from quality_gates.config import QualityConfig, load_config
from quality_gates.github_comment import _inline_body, post_walkthrough
from quality_gates.models import Finding
from quality_gates.review.commands import (
    COMMANDS,
    HELP,
    SheriffCommand,
    parse_sheriff_command,
    run_sheriff,
)
from quality_gates.review.commands import (
    is_paused as sheriff_is_paused,
)
from quality_gates.review.contract import finding_payload
from quality_gates.review.engine import compute_effort, is_paused, render_review
from quality_gates.review.parse import (
    STRICTNESS_THRESHOLDS,
    filter_by_confidence,
    strictness_threshold,
)


def _finding(confidence: float, **kwargs) -> Finding:
    base = {
        "gate": "review",
        "message": "bug",
        "severity": "warning",
        "path": "a.py",
        "line": 1,
        "rule": "logic",
    }
    base.update(kwargs)
    return Finding(confidence=confidence, **base)  # type: ignore[arg-type]


def test_confidence_defaults_to_half() -> None:
    item = Finding(gate="review", message="bug")
    assert item.confidence == 0.5
    assert item.to_dict()["confidence"] == 0.5
    assert finding_payload(item)["confidence"] == 0.5


def test_confidence_legacy_coercion() -> None:
    assert Finding(gate="review", message="x", confidence=None).confidence == 0.5  # type: ignore[arg-type]
    assert Finding(gate="review", message="x", confidence="").confidence == 0.5  # type: ignore[arg-type]
    assert Finding(gate="review", message="x", confidence="HIGH").confidence == 0.9  # type: ignore[arg-type]
    assert Finding(gate="review", message="x", confidence="0.7").confidence == 0.7  # type: ignore[arg-type]


def test_confidence_clamped() -> None:
    assert _finding(9.0).confidence == 1.0
    assert _finding(-2.0).confidence == 0.0


def test_strictness_mapping() -> None:
    assert STRICTNESS_THRESHOLDS == {"quiet": 0.8, "standard": 0.5, "strict": 0.2}
    assert strictness_threshold("quiet") == 0.8
    assert strictness_threshold("standard") == 0.5
    assert strictness_threshold("strict") == 0.2
    assert strictness_threshold("bogus") == 0.5


def test_confidence_filter() -> None:
    findings = [_finding(0.9), _finding(0.6), _finding(0.3)]
    assert len(filter_by_confidence(findings, "quiet")) == 1
    assert len(filter_by_confidence(findings, "standard")) == 2
    assert len(filter_by_confidence(findings, "strict")) == 3
    # Below the strict floor is still dropped.
    assert filter_by_confidence([_finding(0.1)], "strict") == []


def test_effort_formula() -> None:
    # Effort = 1 + min(4, files // 3 + blockers)
    assert compute_effort(0, 0) == 1
    assert compute_effort(3, 0) == 2
    assert compute_effort(0, 2) == 3
    assert compute_effort(30, 10) == 5
    assert 1 <= compute_effort(100, 100) <= 5


def test_walkthrough_header() -> None:
    findings = [_finding(0.9, severity="error", suggestion="fix it")]
    body = render_review(
        findings,
        summary="looks good",
        provider="heuristic",
        languages=["python"],
        resolution={},
        rules=1,
        files=["a.py", "b.py"],
        related=["c.py"],
        effort=2,
    )
    assert "## Walkthrough" in body
    assert "Summary:" in body
    assert "Effort:" in body
    assert "Files:" in body
    assert "Related:" in body
    assert "<details>" in body
    assert "confidence" in body.lower()
    assert "Fix with `/sheriff fix`" in body


def test_inline_body_has_confidence_and_fix(tmp_path: Path) -> None:
    _ = tmp_path
    item = _finding(0.75, suggestion="do x")
    body = _inline_body(item)
    assert "Confidence:" in body
    assert "Fix with `/sheriff fix`" in body
    # Even without suggestion/patch the Fix button text must be present.
    plain = _finding(0.5)
    assert "Fix with `/sheriff fix`" in _inline_body(plain)


def test_post_walkthrough_helper(monkeypatch) -> None:
    monkeypatch.setattr(
        "quality_gates.github_comment.post_pr_comment",
        lambda body: f"posted {len(body)} chars",
    )
    assert "posted" in post_walkthrough("hello")


def test_pause_resume_full_commands_registered() -> None:
    assert {"pause", "resume", "full"} <= set(COMMANDS)
    assert "/sheriff pause" in HELP
    assert "/sheriff resume" in HELP
    assert "/sheriff full" in HELP
    parsed = parse_sheriff_command("/sheriff pause")
    assert isinstance(parsed, SheriffCommand)
    assert parsed is not None and parsed.name == "pause"
    assert parse_sheriff_command("/sheriff resume").name == "resume"  # type: ignore[union-attr]
    assert parse_sheriff_command("/sheriff full").name == "full"  # type: ignore[union-attr]
    assert parse_sheriff_command("/sheriff full").forces_review is True  # type: ignore[union-attr]


def test_pause_resume_verbs(tmp_path: Path) -> None:
    config = QualityConfig()
    code, _ = run_sheriff(
        tmp_path, config, request=parse_sheriff_command("/sheriff pause"), post=False
    )
    assert code == 0
    assert (tmp_path / ".quality-reports" / "sheriff-paused").is_file()
    assert is_paused(tmp_path)
    assert sheriff_is_paused(tmp_path)

    # Engine must skip while paused.
    from quality_gates.review.engine import run_review

    result = run_review(tmp_path, config, ["python"], base="HEAD", post=False)
    assert result.status == "skip"

    code, _ = run_sheriff(
        tmp_path, config, request=parse_sheriff_command("/sheriff resume"), post=False
    )
    assert code == 0
    assert not (tmp_path / ".quality-reports" / "sheriff-paused").exists()
    assert not is_paused(tmp_path)


def test_config_new_knobs_backward_compatible(tmp_path: Path) -> None:
    # Old configs without the knobs still parse with defaults.
    old = load_config(tmp_path)
    assert old.review_strictness == "standard"
    assert old.review_fail_severity == "error"
    assert old.review_ignore_labels == []
    (tmp_path / "quality.toml").write_text(
        '[quality.review]\nstrictness = "quiet"\n'
        'fail_severity = "warning"\n'
        'ignore_labels = ["large-pr"]\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.review_strictness == "quiet"
    assert config.review_fail_severity == "warning"
    assert config.review_ignore_labels == ["large-pr"]
    # Invalid values fall back without breaking.
    (tmp_path / "quality.toml").write_text(
        '[quality.review]\nstrictness = "loud"\nfail_severity = "critical"\n',
        encoding="utf-8",
    )
    fallback = load_config(tmp_path)
    assert fallback.review_strictness == "standard"
    assert fallback.review_fail_severity == "error"
