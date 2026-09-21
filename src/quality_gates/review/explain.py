"""Finding explanation template and diff Q&A helpers."""

from __future__ import annotations

from quality_gates.models import Finding
from quality_gates.review.severity import taxonomy_level


def _confidence_display(value: object) -> tuple[str, bool]:
    """Render confidence and flag speculation for ``str`` or P0 ``float`` input.

    Legacy labels (``HIGH``/``MEDIUM``/``LOW``) keep their exact behavior;
    numeric confidences (P0 ``Finding.confidence`` floats) render as
    ``0.00``-``1.00`` and count as speculative at or below the ``LOW``
    equivalent (``<= 0.3``).
    """
    if value is None or value == "" or isinstance(value, bool):
        return "HIGH", False
    if isinstance(value, (int, float)):
        number = max(0.0, min(1.0, float(value)))
        return f"{number:.2f}", number <= 0.3
    text = str(value).strip() or "HIGH"
    return text, text.upper() == "LOW"


def explain_finding(item: Finding) -> str:
    level = taxonomy_level(item)
    confidence_label, speculative = _confidence_display(item.confidence)
    lines = [
        f"**{item.rule or 'review'}** ({item.severity} · {level}"
        + (" · speculative" if speculative else "")
        + ")",
        "",
        f"What is wrong: {item.message}",
    ]
    if item.reason:
        lines.append(f"Why it matters here: {item.reason}")
    evidence = item.snippet or (f"{item.path}:{item.line}" if item.path else "")
    if evidence:
        lines.append(f"Evidence: `{evidence}`")
    lines.append(f"Confidence: {confidence_label}")
    if item.suggestion:
        lines.append(f"Smallest safe fix: {item.suggestion}")
    return "\n".join(lines)


def explain_diff(question: str, paths: list[str], related: str = "") -> str:
    topic = question.strip() or "What does this change do?"
    files = ", ".join(paths[:12]) or "the current diff"
    extra = f"\n\nRelated context:\n{related}" if related else ""
    return f"{topic}\n\nThis explanation is grounded in {files}.{extra}\n"
