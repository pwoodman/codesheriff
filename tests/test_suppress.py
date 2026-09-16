"""Durable, fingerprint-scoped suppression behaviour."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.ignore import (
    append_ignore,
    apply_ignores,
    find_suppression_rule,
    ignore_path,
    ignore_reason,
    load_ignore_rules,
    remove_suppression,
    suppression_summary,
)
from quality_gates.models import Finding, GateResult
from quality_gates.review.feedback import (
    apply_feedback,
    load_feedback,
    record_feedback,
    should_suppress_rule,
)
from quality_gates.review.parse import fingerprint

SUPPRESS_MODULE = "quality_gates.commands.suppress"


def _finding(path: str = "src/app.py", line: int = 10, rule: str = "logic") -> Finding:
    return Finding(
        gate="review",
        rule=rule,
        path=path,
        line=line,
        severity="error",
        message="suspicious thing",
    )


def _result(*findings: Finding) -> GateResult:
    return GateResult(name="review", status="fail", findings=list(findings))


def test_fingerprint_suppression_matches_only_that_finding(tmp_path: Path) -> None:
    target = _finding(line=10)
    other = _finding(line=200)
    append_ignore(
        tmp_path,
        rule="logic",
        path="src/app.py",
        reason="accepted",
        owner="alice",
        days=None,
        fingerprint=fingerprint(target, bucket=1),
    )
    rules = load_ignore_rules(tmp_path)
    assert ignore_reason(tmp_path, target, rules) is not None
    # A different line of the same rule must NOT be waived.
    assert ignore_reason(tmp_path, other, rules) is None


def test_fingerprint_suppression_does_not_waive_whole_rule(tmp_path: Path) -> None:
    target = _finding(path="src/app.py", line=10, rule="sql-concat")
    elsewhere = _finding(path="src/db.py", line=5, rule="sql-concat")
    append_ignore(
        tmp_path,
        rule="sql-concat",
        reason="known safe",
        owner="bob",
        days=None,
        fingerprint=fingerprint(target, bucket=1),
    )
    rules = load_ignore_rules(tmp_path)
    assert ignore_reason(tmp_path, target, rules) is not None
    assert ignore_reason(tmp_path, elsewhere, rules) is None


def test_apply_ignores_records_suppressions(tmp_path: Path) -> None:
    finding = _finding()
    append_ignore(
        tmp_path,
        rule="logic",
        reason="false positive",
        owner="alice",
        days=None,
        fingerprint=fingerprint(finding, bucket=1),
    )
    result = _result(finding)
    apply_ignores([result], tmp_path)
    assert result.status == "pass"
    assert result.findings == []
    summary = suppression_summary([result])
    assert summary["total"] == 1
    assert summary["by_gate"] == {"review": 1}
    assert summary["items"][0]["reason"].startswith("ignored")


def test_expired_suppression_is_ignored_but_auditable(tmp_path: Path) -> None:
    finding = _finding()
    appended = append_ignore(
        tmp_path,
        rule="logic",
        reason="stale",
        owner="alice",
        days=None,
        fingerprint=fingerprint(finding, bucket=1),
    )
    # Force an already-expired window.
    appended.write_text(
        appended.read_text(encoding="utf-8").replace(
            'reason = "stale"', 'reason = "stale"\nexpires = "2000-01-01T00:00:00Z"'
        ),
        encoding="utf-8",
    )
    assert ignore_reason(tmp_path, finding, load_ignore_rules(tmp_path)) is None
    all_rules = load_ignore_rules(tmp_path, include_expired=True)
    assert any(rule.fingerprint for rule in all_rules)


def test_find_and_remove_suppression(tmp_path: Path) -> None:
    finding = _finding()
    key = fingerprint(finding, bucket=1)
    append_ignore(
        tmp_path,
        rule="logic",
        reason="accepted",
        owner="alice",
        days=None,
        fingerprint=key,
    )
    assert find_suppression_rule(tmp_path, key) is not None
    assert remove_suppression(tmp_path, key) is True
    assert find_suppression_rule(tmp_path, key) is None
    assert remove_suppression(tmp_path, key) is False


def test_remove_preserves_other_blocks(tmp_path: Path) -> None:
    a, b = _finding(line=1), _finding(line=100)
    append_ignore(
        tmp_path,
        rule="logic",
        reason="a",
        owner="alice",
        days=None,
        fingerprint=fingerprint(a, bucket=1),
    )
    append_ignore(
        tmp_path,
        rule="logic",
        reason="b",
        owner="bob",
        days=None,
        fingerprint=fingerprint(b, bucket=1),
    )
    remove_suppression(tmp_path, fingerprint(a, bucket=1))
    rules = load_ignore_rules(tmp_path)
    assert len(rules) == 1
    assert rules[0].fingerprint == fingerprint(b, bucket=1)


def test_ignore_path_prefers_canonical_file(tmp_path: Path) -> None:
    legacy_gate = tmp_path / ".quality-gates-ignore.toml"
    legacy_gate.write_text("[[ignore]]\n", encoding="utf-8")
    assert ignore_path(tmp_path).name == ".quality-gates-ignore.toml"
    legacy = tmp_path / ".quality" / "ignore.toml"
    legacy.parent.mkdir()
    legacy.write_text("[[ignore]]\n", encoding="utf-8")
    assert ignore_path(tmp_path).name == "ignore.toml"
    assert ignore_path(tmp_path).parent.name == ".quality"
    canonical = tmp_path / ".sheriff" / "ignore.toml"
    canonical.parent.mkdir()
    canonical.write_text("[[ignore]]\n", encoding="utf-8")
    assert ignore_path(tmp_path).parent.name == ".sheriff"


def test_committed_feedback_is_merged_and_wins(tmp_path: Path) -> None:
    committed = tmp_path / ".sheriff" / "feedback.json"
    committed.parent.mkdir(parents=True)
    committed.write_text(
        json.dumps({"rules": {"noisy": {"useful": 0, "not_useful": 3, "incorrect": 0}}})
        + "\n",
        encoding="utf-8",
    )
    legacy = tmp_path / ".quality" / "feedback.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"rules": {"noisy": {"useful": 0, "not_useful": 2, "incorrect": 0}}})
        + "\n",
        encoding="utf-8",
    )
    # Local cache has fewer signals; committed values must survive the merge.
    local = tmp_path / ".quality-reports" / "feedback.json"
    local.parent.mkdir(parents=True)
    local.write_text(
        json.dumps({"rules": {"noisy": {"useful": 0, "not_useful": 1, "incorrect": 0}}})
        + "\n",
        encoding="utf-8",
    )
    merged = load_feedback(tmp_path)
    assert merged["rules"]["noisy"]["not_useful"] == 3
    assert should_suppress_rule(tmp_path, "noisy") is True


def test_record_feedback_writes_both_stores(tmp_path: Path) -> None:
    record_feedback(tmp_path, rule="noisy", disposition="not_useful")
    assert (tmp_path / ".sheriff" / "feedback.json").is_file()
    assert (tmp_path / ".quality-reports" / "feedback.json").is_file()


def test_apply_feedback_keeps_security_rules(tmp_path: Path) -> None:
    for _ in range(3):
        record_feedback(tmp_path, rule="sql-concat", disposition="not_useful")
    finding = Finding(gate="review", rule="sql-concat", message="x", severity="error")
    assert apply_feedback(tmp_path, [finding]) == [finding]


def test_suppress_command_add_and_audit(tmp_path: Path, capsys) -> None:
    from quality_gates.commands import suppress as cmd

    finding = _finding()
    key = fingerprint(finding, bucket=1)
    reports = tmp_path / ".quality-reports"
    reports.mkdir(parents=True)
    (reports / "findings-last.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "findings": [
                    {
                        "fingerprint": key,
                        "gate": "review",
                        "rule": "logic",
                        "path": "src/app.py",
                        "line": 10,
                        "message": "suspicious thing",
                        "severity": "error",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    class Args:
        command = "suppress"
        action = "add"
        finding_id = key
        reason = "accepted"
        owner = "alice"
        days = 0
        rule = None
        path = None
        gate = None
        json = False

    assert cmd.handle(Args(), tmp_path, None) == 0
    assert find_suppression_rule(tmp_path, key) is not None
    capsys.readouterr()

    Args.action = "audit"
    Args.owner = ""
    assert cmd.handle(Args(), tmp_path, None) == 0
    out = capsys.readouterr().out
    assert "suppressions:" in out

    Args.action = "remove"
    assert cmd.handle(Args(), tmp_path, None) == 0
    assert find_suppression_rule(tmp_path, key) is None
