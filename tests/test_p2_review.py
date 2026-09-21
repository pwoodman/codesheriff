"""P2 track tests: debate dedup/judge, SheriffScore math, learning, GitLab stub."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.models import Finding, GateResult
from quality_gates.report import build_digest, render_html
from quality_gates.review import bench as bench_mod
from quality_gates.review.bench import run_heuristic_suite, sheriff_score
from quality_gates.review.debate import PERSONAS, run_debate, wants_debate
from quality_gates.review.gitlab import (
    gitlab_env_present,
    maybe_post_gitlab_review,
    post_gitlab_review,
)
from quality_gates.review.learning import (
    apply_feedback,
    load_thumbs,
    review_learn_hook,
)


def _finding(
    path: str = "src/app.py",
    line: int = 10,
    rule: str = "logic",
    message: str = "something is wrong",
    confidence: float | str | None = None,
) -> Finding:
    kwargs: dict = {}
    if confidence is not None:
        kwargs["confidence"] = confidence
    return Finding(
        gate="review",
        message=message,
        severity="warning",
        path=path,
        line=line,
        rule=rule,
        **kwargs,
    )


# --- debate: dedup + speculative judge -------------------------------------


def test_debate_dedups_by_fingerprint() -> None:
    dupes = {
        "security": [_finding(message="short")],
        "performance": [_finding(message="a much longer message with evidence")],
        "maintainability": [],
    }
    verdict = run_debate(dupes)
    assert len(verdict["findings"]) == 1
    assert verdict["findings"][0].message.startswith("a much longer")
    assert verdict["votes"] and set(verdict["votes"].popitem()[1]) == {
        "performance",
        "security",
    }
    assert any("dedup" in line for line in verdict["discourse"])


def test_debate_drops_speculative_unless_two_personas_agree() -> None:
    solo = run_debate({"security": [_finding(confidence="0.1")]})
    assert solo["findings"] == []
    assert len(solo["dropped"]) == 1
    assert any("dropped speculative" in line for line in solo["discourse"])

    agreed = run_debate(
        {
            "security": [_finding(confidence="0.1")],
            "performance": [_finding(confidence="0.2")],
        }
    )
    assert len(agreed["findings"]) == 1
    assert agreed["dropped"] == []
    assert any("2 personas agree" in line for line in agreed["discourse"])


def test_debate_keeps_confident_and_unmarked() -> None:
    verdict = run_debate(
        {
            "security": [_finding(confidence="0.9")],
            "maintainability": [_finding(path="src/other.py", confidence="HIGH")],
        }
    )
    assert len(verdict["findings"]) == 2
    assert verdict["personas"] == list(PERSONAS)


def test_wants_debate_reads_raw_config() -> None:
    from types import SimpleNamespace

    assert wants_debate(
        SimpleNamespace(
            review_mode="auto", raw={"quality": {"review": {"mode": "debate"}}}
        )
    )
    assert not wants_debate(SimpleNamespace(review_mode="single", raw={}))


# --- SheriffScore math ------------------------------------------------------


def test_sheriff_score_perfect_and_zero() -> None:
    assert sheriff_score(1.0, 0.0, 1.0, 0.0, 0.0) == 1.0
    assert sheriff_score(0.0, 10.0, 0.0, 300.0, 50.0) == 0.0


def test_sheriff_score_weights() -> None:
    expected = round(
        0.35 * 0.8
        + 0.25 * (1 - min(1, 2 / 10))
        + 0.20 * 0.5
        + 0.10 * max(0, 1 - 30 / 300)
        + 0.10 * max(0, 1 - 5 / 50),
        4,
    )
    assert sheriff_score(0.8, 2.0, 0.5, 30.0, 5.0) == expected


def test_heuristic_suite_reports_sheriff_score() -> None:
    suite = run_heuristic_suite(bench_mod.bundled_bench_dir())
    assert "sheriff_score" in suite
    assert "sheriff_score_inputs" in suite
    assert 0.0 <= suite["sheriff_score"] <= 1.0
    assert suite["sheriff_score_inputs"]["p50_s"] == 0.0


# --- learning: thumbs boost/penalty -----------------------------------------


def test_load_thumbs_normalises_votes(tmp_path: Path) -> None:
    path = tmp_path / "thumbs.json"
    path.write_text(
        json.dumps({"a|b|1": 5, "c|d|2": -2, "zero": 0, "junk": "x", "": 1}),
        encoding="utf-8",
    )
    assert load_thumbs(path) == {"a|b|1": 1, "c|d|2": -1}
    assert load_thumbs(tmp_path / "missing.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    assert load_thumbs(broken) == {}


def test_learning_boost_and_penalty() -> None:
    good = _finding(confidence="0.5")
    bad = _finding(path="src/other.py", confidence="0.5")
    other = _finding(path="src/third.py", confidence="0.5")
    from quality_gates.review.parse import fingerprint

    thumbs = {
        fingerprint(good, bucket=1): 1,
        fingerprint(bad, bucket=1): -1,
    }
    apply_feedback([good, bad, other], thumbs)
    assert float(good.confidence) > 0.5
    assert float(bad.confidence) < 0.5
    assert float(other.confidence) == 0.5


def test_review_learn_hook_reads_thumbs_file(tmp_path: Path, monkeypatch) -> None:
    report_dir = tmp_path / ".quality-reports"
    report_dir.mkdir()
    target = _finding(confidence="0.5")
    from quality_gates.review.parse import fingerprint

    (report_dir / "thumbs.json").write_text(
        json.dumps({fingerprint(target, bucket=1): 1}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    result = review_learn_hook(tmp_path, findings=[target])
    assert result["boosted"] == 1
    assert result["applied"] == 1
    assert float(target.confidence) > 0.5


# --- gitlab stub: never crashes ----------------------------------------------


def test_gitlab_stub_no_crash_without_env(monkeypatch) -> None:
    for name in (
        "GITLAB_TOKEN",
        "CI_JOB_TOKEN",
        "CI_MERGE_REQUEST_IID",
        "CI_PROJECT_ID",
        "CI_API_V4_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    assert not gitlab_env_present()
    assert maybe_post_gitlab_review("hello", [_finding()]) == []
    notes = post_gitlab_review("hello", [_finding()])
    assert len(notes) == 1 and "skipped" in notes[0]


# --- report_html: Change-Stack-lite -------------------------------------------


def test_change_stack_cohorts_and_code_peek() -> None:
    results = [
        GateResult(
            name="review",
            status="pass",
            findings=[
                Finding(
                    gate="review",
                    message="x",
                    severity="warning",
                    path="src/app.py",
                    line=1,
                ),
                Finding(
                    gate="review",
                    message="y",
                    severity="warning",
                    path="tooling/cli.py",
                    line=2,
                ),
            ],
        )
    ]
    page = render_html(build_digest(results, policy="enforce"))
    assert "Change stack" in page
    assert "Code Peek" in page
    assert "github.com/search" in page
    assert "src" in page and "tooling" in page
