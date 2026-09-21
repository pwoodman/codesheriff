from __future__ import annotations

from pathlib import Path

from quality_gates.models import Finding, GateResult
from quality_gates.review.engine import render_review
from quality_gates.review.engine import run_review as _engine_run_review
from quality_gates.review.heuristic import heuristic_review as _heuristic_review

__all__ = ["_heuristic_review", "attempt_prove", "render_review", "run_review"]

PROVE_LIMIT = 3
PROVE_REPORT = "prove.md"


def _prove_snippet(index: int, finding: Finding) -> str:
    loc = finding.path or "repo"
    if finding.line:
        loc = f"{loc}:{finding.line}"
    rule = finding.rule or "finding"
    message = (finding.message or "").strip().replace("\n", " ")[:300]
    suggestion = (finding.suggestion or "").strip().replace("\n", " ")[:300]
    func = f"test_prove_{index}_{rule.replace('-', '_').replace('/', '_')}"
    func = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in func)[:64]
    lines = [
        f"def {func}():",
        f'    """Best-effort T-REX-lite reproduction for {loc} [{rule}].',
        "",
        f"    Finding: {message or '(no message)'}",
    ]
    if suggestion:
        lines.append(f"    Suggestion: {suggestion}")
    lines.extend(
        [
            '    """',
            f"    # target: {loc}",
            f"    # rule: {rule}",
            "    # NOTE: generated, not executed. Replace assert with a real check.",
            "    assert True",
            "",
        ]
    )
    return "\n".join(lines)


def attempt_prove(
    root: Path,
    findings: list[Finding],
    *,
    limit: int = PROVE_LIMIT,
) -> list[str]:
    """Best-effort T-REX-lite: draft pytest snippets for the top findings.

    Safe by construction: no network, no subprocess, no exec — only writes
    snippet *text* to ``.quality-reports/prove.md``. Never raises.
    """
    notes: list[str] = []
    try:
        from contextlib import suppress

        top = list(findings or [])[: max(0, limit)]
        out = Path(root) / ".quality-reports" / PROVE_REPORT
        with suppress(OSError):
            out.parent.mkdir(parents=True, exist_ok=True)
        parts = [
            "# Prove attempts (T-REX-lite, best-effort)",
            "",
            "No snippets were executed. Each block below is a pytest *draft* "
            "for a human or agent to confirm the finding.",
            "",
        ]
        if not top:
            parts.append("No findings to prove.")
            parts.append("")
        for idx, item in enumerate(top, start=1):
            loc = f"{item.path or 'repo'}:{item.line or '-'}"
            parts.append(f"## Attempt {idx}: `{loc}` `{item.rule or 'finding'}`")
            parts.append("")
            parts.append(f"- severity: {item.severity}")
            parts.append(f"- message: {(item.message or '').strip()[:400]}")
            if item.suggestion:
                parts.append(f"- suggestion: {item.suggestion.strip()[:400]}")
            parts.append("")
            parts.append("```python")
            parts.append(_prove_snippet(idx, item))
            parts.append("```")
            parts.append("")
            notes.append(
                f"prove_attempt {idx}/{len(top)}: {loc} "
                f"({item.rule or 'finding'}) snippet recorded"
            )
        try:
            out.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
        except OSError as exc:
            notes.append(f"prove_attempt skipped: cannot write prove.md ({exc})")
            return notes
        notes.append(
            f"prove: wrote .quality-reports/{PROVE_REPORT} with {len(top)} attempt(s)"
        )
        return notes
    except Exception as exc:  # never fail the build
        return [f"prove_attempt skipped: {exc}"]


def run_review(
    root: Path,
    config,
    languages: list[str],
    *,
    base: str | None = None,
    post: bool = False,
    prior: list[GateResult] | None = None,
    prove: bool = False,
    **kwargs,
) -> GateResult:
    """Backward-compat wrapper around the review engine with ``--prove`` support."""
    try:
        result = _engine_run_review(
            root, config, languages, base=base, post=post, prior=prior, **kwargs
        )
    except TypeError:
        result = _engine_run_review(
            root, config, languages, base=base, post=post, prior=prior
        )
    if prove or bool(getattr(config, "prove", False)):
        try:
            notes = attempt_prove(root, result.findings)
        except Exception as exc:  # never fail the build
            notes = [f"prove_attempt skipped: {exc}"]
        result.notes.extend(notes)
    return result
