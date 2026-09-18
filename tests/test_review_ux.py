"""Tests for CodeRabbit-superiority review UX: Mermaid diagrams, 1-click suggestions, and tone calibration."""

from quality_gates.models import Finding
from quality_gates.review.diagrams import (
    generate_mermaid_flowchart,
    generate_mermaid_sequence_diagram,
)
from quality_gates.review.summary import render_structured_summary
from quality_gates.review.ux import (
    answer_pr_review_comment,
    calibrate_finding_tone,
    format_github_suggestion,
)


def test_mermaid_diagrams_generation():
    paths = [
        "src/api/routes.py",
        "src/services/billing.py",
        "src/models/user.py",
    ]

    seq_diag = generate_mermaid_sequence_diagram(paths)
    assert "```mermaid" in seq_diag
    assert "sequenceDiagram" in seq_diag
    assert "routes_py" in seq_diag
    assert "billing_py" in seq_diag
    assert "user_py" in seq_diag

    flow_diag = generate_mermaid_flowchart(paths)
    assert "```mermaid" in flow_diag
    assert "flowchart TD" in flow_diag


def test_github_1click_suggestion():
    orig = "def add(a, b): return a + b"
    valid_fix = "def add(a: int, b: int) -> int:\n    return a + b"
    block = format_github_suggestion(orig, valid_fix, language="python")
    assert block.is_valid_syntax is True
    assert "```suggestion" in block.github_markdown
    assert "def add(a: int, b: int) -> int:" in block.github_markdown

    # Invalid syntax check
    invalid_fix = "def broken( "
    bad_block = format_github_suggestion(orig, invalid_fix, language="python")
    assert bad_block.is_valid_syntax is False


def test_tone_calibration():
    msg = "Variable 'user' is used before assignment"
    rule = "lint/unbound-local"

    assertive = calibrate_finding_tone(msg, rule, tone="assertive")
    assert "Blocking Quality Requirement" in assertive
    assert "must be resolved" in assertive

    collab = calibrate_finding_tone(msg, rule, tone="collaborative")
    assert "Suggestion" in collab
    assert "Would you like to adjust this" in collab

    edu = calibrate_finding_tone(
        msg,
        rule,
        tone="educational",
        rationale="Unbound variables raise UnboundLocalError at runtime.",
    )
    assert "Consideration" in edu
    assert "Why this matters" in edu
    assert "UnboundLocalError" in edu


def test_conversational_pr_response():
    # User asks 'why'
    resp_why = answer_pr_review_comment(
        "Why is this required?",
        "security/sql-injection",
        code_context="cursor.execute(f'SELECT {id}')",
    )
    assert "Rule `security/sql-injection` ensures" in resp_why
    assert "cursor.execute" in resp_why

    # User asks about suppression
    resp_ignore = answer_pr_review_comment(
        "Can we ignore or suppress this?",
        "audit-48",
    )
    assert "codesheriff: ignore" in resp_ignore


def test_render_structured_summary_includes_diagram():
    findings = [
        Finding(
            gate="review",
            message="Unchecked None return",
            severity="warning",
            path="src/api.py",
            line=42,
        )
    ]
    paths = ["src/api.py", "src/service.py"]
    summary = render_structured_summary(
        intent="feature",
        risk="low",
        signal="safe to merge",
        findings=findings,
        paths=paths,
        languages=["python"],
    )
    assert "### Control Flow Diagram" in summary
    assert "sequenceDiagram" in summary
