"""CodeRabbit-superiority: 1-click verified suggestions, tone calibration, and conversational PR UX.

Formats GitHub-compatible 1-click suggestion blocks with transactional syntax verification,
calibrates review persona/tone, and handles conversational PR review comment threads.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Literal

ReviewTone = Literal["assertive", "collaborative", "educational"]


@dataclass
class SuggestionBlock:
    original_code: str
    suggested_code: str
    is_valid_syntax: bool
    github_markdown: str


def format_github_suggestion(
    original_code: str,
    suggested_code: str,
    language: str = "python",
) -> SuggestionBlock:
    """Format a 1-click GitHub suggestion block with transactional syntax verification."""
    clean_suggestion = suggested_code.strip("\r\n")

    # Transactional syntax verification for Python
    valid_syntax = True
    if language.lower() == "python":
        try:
            ast.parse(clean_suggestion)
        except SyntaxError:
            valid_syntax = False

    # GitHub 1-click suggestion markdown format
    md = f"```suggestion\n{clean_suggestion}\n```"

    return SuggestionBlock(
        original_code=original_code,
        suggested_code=clean_suggestion,
        is_valid_syntax=valid_syntax,
        github_markdown=md,
    )


def calibrate_finding_tone(
    message: str,
    rule: str,
    tone: ReviewTone = "collaborative",
    rationale: str = "",
) -> str:
    """Format finding explanation according to review tone persona:

    - assertive: direct, uncompromising on quality gate requirements
    - collaborative: pair-programmer peer, constructive and gentle
    - educational: explains deep principles, root causes, and best practices
    """
    clean_msg = message.strip()

    if tone == "assertive":
        return f"**Blocking Quality Requirement** (`{rule}`): {clean_msg}. This must be resolved before merging to preserve codebase invariants."

    if tone == "educational":
        edu_lines = [
            f"**Consideration (`{rule}`)**: {clean_msg}",
            "",
            "**Why this matters**:",
            rationale
            or "Maintaining clean boundaries prevents hidden runtime defects and cascading failures across services.",
            "",
            "**Recommended pattern**: Follow the suggested fix to adhere to repository design conventions.",
        ]
        return "\n".join(edu_lines)

    # collaborative (default)
    return f"**Suggestion (`{rule}`)**: {clean_msg}. Would you like to adjust this to keep our quality gates green?"


def answer_pr_review_comment(
    user_comment: str,
    finding_rule: str,
    code_context: str = "",
    tone: ReviewTone = "collaborative",
) -> str:
    """Generate an evidence-backed conversational response to a developer's PR review question."""
    lower = user_comment.lower()

    if any(q in lower for q in ["why", "reason", "purpose", "how come"]):
        return (
            f"Thanks for asking! Rule `{finding_rule}` ensures that this change doesn't introduce "
            f"subtle runtime bugs or break consumers in other files. In this context:\n\n"
            f"```\n{code_context[:300]}\n```\n\n"
            f"Applying the recommended pattern ensures type safety and predictable execution."
        )

    if any(q in lower for q in ["ignore", "suppress", "false positive", "skip"]):
        return (
            f"If this is an intentional design choice for this pull request, you can add an inline suppression comment:\n"
            f"`# codesheriff: ignore[{finding_rule}]` above the line, or add the rule to "
            f"`ignore_rules` in `quality.toml`."
        )

    return (
        f"Regarding rule `{finding_rule}`: The goal is to keep code reliability high. "
        f"If the current implementation is intentional, feel free to add a brief comment or test covering this edge case."
    )
