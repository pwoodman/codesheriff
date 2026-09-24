from __future__ import annotations

from pathlib import Path

from quality_gates.models import Finding
from quality_gates.review.aacr_bench import (
    AACRCase,
    AACRIssue,
    render_competitor_comparison_markdown,
    score_aacr_cases,
)


def test_aacr_issue_matching() -> None:
    issue = AACRIssue(
        issue_id="issue-001",
        file_path="src/service/auth.py",
        line_start=40,
        line_end=45,
        category="security",
        severity="high",
        description="SQL injection in raw query",
        needles=["sql", "injection", "query"],
    )

    hit = Finding(
        gate="review",
        path="src/service/auth.py",
        line=42,
        message="Possible SQL injection in user query",
        rule="security/sql",
    )
    assert issue.matches(hit)

    wrong_line = Finding(
        gate="review",
        path="src/service/auth.py",
        line=90,
        message="Possible SQL injection",
        rule="security/sql",
    )
    assert not issue.matches(wrong_line)

    wrong_file = Finding(
        gate="review",
        path="src/service/utils.py",
        line=42,
        message="Possible SQL injection",
        rule="security/sql",
    )
    assert not issue.matches(wrong_file)


def test_score_aacr_cases() -> None:
    cases = [
        AACRCase(
            case_id="case-1",
            repo="org/repo-a",
            pr_id=101,
            language="python",
            diff="",
            ground_truth=[
                AACRIssue(
                    issue_id="gt-1",
                    file_path="main.py",
                    line_start=10,
                    line_end=15,
                    category="correctness",
                    severity="high",
                    description="Null dereference",
                    needles=["null", "none"],
                )
            ],
        ),
        AACRCase(
            case_id="case-2",
            repo="org/repo-b",
            pr_id=202,
            language="typescript",
            diff="",
            ground_truth=[
                AACRIssue(
                    issue_id="gt-2",
                    file_path="app.ts",
                    line_start=25,
                    line_end=28,
                    category="security",
                    severity="critical",
                    description="XSS sink",
                    needles=["xss", "innerhtml"],
                )
            ],
        ),
    ]

    findings_by_case = {
        "case-1": [
            Finding(
                gate="review",
                path="main.py",
                line=12,
                message="Potential None dereference on user input",
                rule="correctness",
            )
        ],
        "case-2": [
            Finding(
                gate="review",
                path="app.ts",
                line=26,
                message="DOM XSS vulnerability via innerHTML",
                rule="security/xss",
            ),
            Finding(
                gate="review",
                path="app.ts",
                line=50,
                message="Spurious nitpick",
                rule="style",
            ),
        ],
    }

    scorecard = score_aacr_cases(cases, findings_by_case)
    assert scorecard.total_cases == 2
    assert scorecard.total_ground_truth == 2
    assert scorecard.total_reported == 3
    assert scorecard.true_positives == 2
    assert scorecard.false_positives == 1
    assert scorecard.false_negatives == 0
    assert scorecard.recall == 1.0
    assert scorecard.precision == round(2 / 3, 4)
    assert scorecard.f1 > 0.75
    assert scorecard.token_ratio_vs_baseline < 0.10


def test_render_competitor_comparison_markdown() -> None:
    md = render_competitor_comparison_markdown()
    assert "The Code Sheriff" in md
    assert "Alibaba Open Code Review" in md
    assert "Cloudflare Security Audit" in md
    assert "CodeRabbit" in md
    assert "Greptile" in md
    assert "Coverage Ledger" in md
    assert "Adversarial Disprover" in md


def test_run_aacr_evaluation(tmp_path: Path) -> None:
    from quality_gates.review.aacr_bench import run_aacr_evaluation

    res = run_aacr_evaluation(tmp_path)
    assert "scorecard" in res
    assert "comparison_matrix_markdown" in res
    assert res["scorecard"]["f1"] == 1.0
    scorecard_path = tmp_path / ".quality-reports" / "eval" / "AACR-SCORECARD.md"
    assert scorecard_path.exists()


def test_canonical_aacr_suite_not_empty() -> None:
    from quality_gates.review.aacr_bench import get_canonical_aacr_suite

    suite = get_canonical_aacr_suite()
    assert len(suite) > 0


def test_run_aacr_hard_evaluation(tmp_path: Path) -> None:
    from quality_gates.review.aacr_bench import (
        get_hard_aacr_suite,
        render_hard_comparison_markdown,
        run_aacr_hard_evaluation,
    )

    suite = get_hard_aacr_suite()
    assert len(suite) == 6
    # Check that distractors are included with empty ground truth
    distractors = [c for c in suite if len(c.ground_truth) == 0]
    assert len(distractors) == 2

    res = run_aacr_hard_evaluation(tmp_path)
    assert res["scorecard"]["precision"] == 1.0
    assert res["scorecard"]["recall"] == 1.0
    assert res["scorecard"]["f1"] == 1.0
    hard_scorecard_path = (
        tmp_path / ".quality-reports" / "eval" / "AACR-HARD-SCORECARD.md"
    )
    assert hard_scorecard_path.exists()

    md = render_hard_comparison_markdown()
    assert "Hard Precision" in md
    assert "Distractor Trap Resistance" in md
