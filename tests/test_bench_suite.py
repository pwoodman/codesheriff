"""SheriffBench: precision, determinism, suppression drift, and termination."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.ignore import (
    IgnoreRule,
    anchor_for,
    apply_ignores,
    load_ignore_rules,
)
from quality_gates.models import Finding, GateResult
from quality_gates.review.evalbench import (
    render_sheriff_scorecard,
    retriage_score,
    run_sheriff_suite,
    termination_score,
    write_sheriff_scorecard,
)
from quality_gates.review.parse import fingerprint


def test_sheriffbench_meets_competitor_bar(tmp_path: Path) -> None:
    payload = run_sheriff_suite(tmp=tmp_path)
    assert payload["failed"] == []
    assert payload["recall"] == 1.0
    assert payload["hard_negative_pass"] == 1.0
    assert payload["determinism"] == 1.0
    assert payload["contract_compliance"] == 1.0
    assert (payload["mean_precision"] or 0) >= 0.6


def test_retriage_rate_is_zero_across_the_corpus(tmp_path: Path) -> None:
    """The headline claim: accepted findings do not come back after a line shift."""
    report = retriage_score(tmp_path)
    assert report["cases"] >= 10
    assert report["held"] == report["cases"]
    assert report["retriage_rate"] == 0.0


def test_termination_escalates_to_a_human(tmp_path: Path) -> None:
    report = termination_score(tmp_path)
    assert report["stalled"] is True
    assert report["iterations_to_stall"] == 3


def test_suppression_survives_line_drift(tmp_path: Path) -> None:
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = eval(user_input)\n", encoding="utf-8")

    original = Finding(
        gate="review",
        message="eval() on untrusted input is a code-injection risk",
        path="src/app.py",
        line=1,
        rule="unsafe-api",
    )
    rule = IgnoreRule(
        rule="unsafe-api",
        path="src/app.py",
        reason="accepted false positive",
        fingerprint=fingerprint(original, bucket=1),
        anchor=anchor_for(original, tmp_path),
    )
    assert rule.anchor

    source.write_text(
        "# unrelated header\n\n\nvalue = eval(user_input)\n", encoding="utf-8"
    )
    drifted = Finding(
        gate="review",
        message="eval() on untrusted input is a code-injection risk",
        path="src/app.py",
        line=4,
        rule="unsafe-api",
        snippet="value = eval(user_input)",
    )
    result = GateResult(name="review", status="fail", findings=[drifted])
    apply_ignores([result], tmp_path, extra=[rule])
    assert result.findings == []
    assert result.evidence["suppressed"][0]["reason"].endswith(
        "(matched after line drift)"
    )


def test_suppression_does_not_leak_to_a_different_location(tmp_path: Path) -> None:
    """Accepting one hit must not waive the same rule elsewhere in the repo."""
    rule = IgnoreRule(
        rule="unsafe-api",
        path="src/a.py",
        reason="accepted",
        fingerprint="src/a.py|unsafe-api|0",
        anchor="deadbeefdeadbeef",
    )
    other = Finding(
        gate="review",
        message="eval() on untrusted input is a code-injection risk",
        path="src/b.py",
        line=1,
        rule="unsafe-api",
        snippet="value = eval(user_input)",
    )
    result = GateResult(name="review", status="fail", findings=[other])
    apply_ignores([result], tmp_path, extra=[rule])
    assert len(result.findings) == 1


def test_suppression_expires_and_is_reported(tmp_path: Path) -> None:
    path = tmp_path / ".sheriff" / "ignore.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "[[ignore]]\n"
        'rule = "unsafe-api"\n'
        'path = "src/app.py"\n'
        'reason = "accepted"\n'
        'expires = "2000-01-01T00:00:00Z"\n',
        encoding="utf-8",
    )
    assert load_ignore_rules(tmp_path) == []
    assert len(load_ignore_rules(tmp_path, include_expired=True)) == 1


def test_scorecard_renders_and_persists(tmp_path: Path) -> None:
    payload = run_sheriff_suite(tmp=tmp_path)
    markdown = render_sheriff_scorecard(payload)
    assert "re-triage rate" in markdown
    assert "recall" in markdown
    dest = write_sheriff_scorecard(tmp_path, payload)
    assert dest.is_file()
    saved = json.loads(dest.read_text(encoding="utf-8"))
    assert saved["suite"] == "sheriffbench"


def test_eval_cli_sheriffbench(capsys, tmp_path: Path, monkeypatch) -> None:
    from quality_gates.cli import main

    monkeypatch.chdir(tmp_path)
    code = main(["eval", "--suite", "sheriffbench"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["sheriffbench"]["failed"] == []
    assert (tmp_path / ".quality-reports" / "eval" / "SHERIFFBENCH.json").is_file()
