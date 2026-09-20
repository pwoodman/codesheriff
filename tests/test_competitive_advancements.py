from pathlib import Path

from quality_gates.commands.ask import query_repo
from quality_gates.commands.bypass import is_bypass_active, record_bypass
from quality_gates.config import QualityConfig
from quality_gates.models import Finding, GateResult
from quality_gates.policy import apply_policy
from quality_gates.review.evalbench import calculate_rsvi
from quality_gates.review.external_eval import target_benchmark_repositories
from quality_gates.review.ux import (
    answer_pr_review_comment,
    format_github_suggestion,
    partition_findings_for_ux,
)


def test_calculate_rsvi():
    res = calculate_rsvi(
        r_crit=1.0,
        false_positive_rate=0.0,
        r_multi=1.0,
        a_fix=1.0,
        b_false=0.0,
    )
    assert res["rsvi"] == 100.0

    # Test realistic balanced score
    res_real = calculate_rsvi(
        r_crit=0.95,
        false_positive_rate=0.05,
        r_multi=0.90,
        a_fix=0.90,
        b_false=0.05,
    )
    assert res_real["rsvi"] >= 90.0


def test_target_benchmark_repositories():
    repos = target_benchmark_repositories()
    assert len(repos) == 3
    names = {r["repo"] for r in repos}
    assert "tiangolo/fastapi" in names
    assert "trpc/trpc" in names
    assert "cli/cli" in names


def test_ask_query_repo(tmp_path: Path):
    py_file = tmp_path / "auth.py"
    py_file.write_text(
        "def authenticate_user(token: str):\n    return True\n", encoding="utf-8"
    )
    config = QualityConfig()
    result = query_repo(tmp_path, config, "authenticate_user")
    assert result["count"] >= 1
    assert any("authenticate_user" in r.get("name", "") for r in result["results"])


def test_emergency_bypass_and_policy(tmp_path: Path, monkeypatch):
    config = QualityConfig()
    findings = [Finding(gate="security", message="potential issue", severity="error")]
    results = [GateResult(name="security", status="fail", findings=findings)]

    # Initially without bypass, adopt/enforce fails
    _out_results, _policy = apply_policy(list(results), tmp_path, config)
    # Now record bypass
    record_bypass(tmp_path, reason="incident hotfix P0", author="alice", pr="123")
    assert is_bypass_active(tmp_path) is True

    # Re-evaluating policy demotes failure for bypass
    bypassed_results, bypassed_policy = apply_policy(
        [
            GateResult(
                name="security",
                status="fail",
                findings=[Finding(gate="security", message="err", severity="error")],
            )
        ],
        tmp_path,
        config,
    )
    assert bypassed_policy == "bypass"
    assert bypassed_results[0].status == "pass"


def test_ux_partition_and_suggestion():
    blocker = Finding(
        gate="security", message="SQL injection", severity="error", rule="cwe-89"
    )
    nit = Finding(
        gate="format", message="line too long", severity="warning", rule="line-length"
    )
    blockers, collapsed = partition_findings_for_ux([blocker, nit])
    assert len(blockers) == 1
    assert blockers[0].rule == "cwe-89"
    assert len(collapsed) == 1
    assert collapsed[0].rule == "line-length"

    # Transactional suggestion check
    good_sugg = format_github_suggestion("x = 1", "x = 2", language="python")
    assert good_sugg.is_valid_syntax is True
    assert "```suggestion" in good_sugg.github_markdown

    bad_sugg = format_github_suggestion("def f():", "def f() broken", language="python")
    assert bad_sugg.is_valid_syntax is False


def test_answer_pr_review_conversational():
    resp_bypass = answer_pr_review_comment(
        "/sheriff bypass for critical hotfix", "sec-01"
    )
    assert "codesheriff bypass" in resp_bypass
    resp_resolve = answer_pr_review_comment("/sheriff resolve", "sec-01")
    assert "marked resolved" in resp_resolve
