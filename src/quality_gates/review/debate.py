"""Multi-persona debate review (P2).

Three personas (``security``, ``performance``, ``maintainability``) review the
same diff independently. Their findings are then *judged*:

* dedup by :func:`quality_gates.review.parse.fingerprint`,
* drop speculative findings (confidence < 0.3) unless 2+ personas agree.

``run_debate`` is the pure merge/judge step and needs no LLM. Use
``run_debate_review`` for the LLM-backed variant: it prompts one persona per
call and falls back to a single generic pass when the client is missing or a
persona call fails, so ``review.mode = "debate"`` never breaks the review
gate. All LLM access here goes through the client's ``complete`` method, so
:mod:`quality_gates.review.llm` does not need any edit.

``wants_debate`` detects ``review.mode = "debate"`` without touching the
config loader: :func:`quality_gates.config.load_config` normalises unknown
modes to ``"auto"``, but the raw ``quality.toml`` value survives on
``config.raw``, which is checked first (then ``QUALITY_REVIEW_MODE``).
"""

from __future__ import annotations

import os
from typing import Any

from quality_gates.models import Finding
from quality_gates.review.parse import fingerprint

PERSONAS: tuple[str, ...] = ("security", "performance", "maintainability")

#: Findings with a numeric confidence below this are speculative and are
#: dropped unless at least two personas flagged the same fingerprint.
SPECULATIVE_THRESHOLD = 0.3

_PERSONA_BRIEFS = {
    "security": (
        "You are the SECURITY persona. Flag injection, auth/authz gaps, "
        "secrets, unsafe APIs, missing validation, and error paths that leak "
        "information. Ignore style and performance."
    ),
    "performance": (
        "You are the PERFORMANCE persona. Flag N+1 queries, needless "
        "allocation or copies, blocking I/O on hot paths, missing caches or "
        "indexes, and algorithmic blowups. Ignore style and security."
    ),
    "maintainability": (
        "You are the MAINTAINABILITY persona. Flag dead code, tangled "
        "control flow, missing tests for new branches, misleading names, "
        "and blast radius (callers not updated). Ignore style and security."
    ),
}

_TEXT_CONFIDENCE = {"high": 0.9, "medium": 0.6, "low": 0.3}


def confidence_value(finding: Finding) -> float | None:
    """Return the numeric confidence of a finding, if parseable.

    Accepts floats (``Finding.confidence``), numeric strings (``"0.8"``),
    and HIGH/MEDIUM/LOW labels. Returns ``None`` when the finding carries
    no usable confidence signal.
    """
    raw = finding.confidence
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return max(0.0, min(1.0, float(raw)))
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    try:
        return max(0.0, min(1.0, float(text)))
    except (TypeError, ValueError):
        return _TEXT_CONFIDENCE.get(text)


def _conf(finding: Finding, default: float = 0.5) -> float:
    """Numeric confidence as a float, robust to ``str | float | None``.

    ``Finding.confidence`` is ``str | None`` on this base but the P0 track
    moves it to ``float`` (default 0.5, with coercion); this helper accepts
    floats, numeric strings, and HIGH/MEDIUM/LOW labels, falling back to
    ``default`` when no usable signal is present.
    """
    value = confidence_value(finding)
    return default if value is None else value


def wants_debate(config: Any) -> bool:
    """Return True when ``review.mode = "debate"`` was requested.

    Reads the raw ``quality.toml`` value preserved on ``config.raw`` (the
    typed ``config.review_mode`` normalises unknown modes to ``"auto"``),
    falling back to the ``QUALITY_REVIEW_MODE`` environment variable.
    """
    raw = getattr(config, "raw", None)
    if isinstance(raw, dict):
        review = (raw.get("quality") or {}).get("review") or {}
        if str(review.get("mode") or "").strip().lower() == "debate":
            return True
    if os.environ.get("QUALITY_REVIEW_MODE", "").strip().lower() == "debate":
        return True
    return str(getattr(config, "review_mode", "") or "").strip().lower() == "debate"


def run_debate(
    findings_by_persona: dict[str, list[Finding]],
    *,
    threshold: float = SPECULATIVE_THRESHOLD,
) -> dict[str, Any]:
    """Merge per-persona findings and judge them.

    * Dedup by :func:`fingerprint` (exact line, ``bucket=1``).
    * Keep the longest message among duplicates (richest evidence wins).
    * Drop speculative findings (confidence < ``threshold``) unless 2+
      personas flagged the same fingerprint.
    * Findings with no parseable confidence are kept (not speculative).

    Returns ``{"findings": [...], "discourse": [...], "dropped": [...],
    "votes": {fingerprint: [personas]}}``. The discourse log records every
    dedup collapse and judge decision for auditability.
    """
    groups: dict[str, list[tuple[str, Finding]]] = {}
    order: list[str] = []
    for persona in PERSONAS:
        seen: set[str] = set()
        for item in findings_by_persona.get(persona, []) or []:
            key = fingerprint(item, bucket=1)
            if key in seen:
                continue
            seen.add(key)
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((persona, item))

    merged: list[Finding] = []
    dropped: list[dict[str, Any]] = []
    discourse: list[str] = []
    votes: dict[str, list[str]] = {}
    for key in order:
        hits = groups[key]
        personas = sorted({persona for persona, _ in hits})
        votes[key] = personas
        chosen = max((item for _, item in hits), key=lambda item: len(item.message))
        if len(hits) > 1:
            discourse.append(
                f"dedup {key}: {len(hits)} duplicate(s) from "
                f"{', '.join(personas)} collapsed into one"
            )
        conf = _conf(chosen)
        if conf < threshold and len(personas) < 2:
            dropped.append(
                {
                    "fingerprint": key,
                    "personas": personas,
                    "confidence": conf,
                    "message": chosen.message,
                }
            )
            discourse.append(
                f"judge {key}: dropped speculative finding "
                f"(confidence {conf:.2f} < {threshold}, "
                f"only {', '.join(personas)} flagged it)"
            )
            continue
        if conf < threshold:
            discourse.append(
                f"judge {key}: kept speculative finding "
                f"(confidence {conf:.2f}) — {len(personas)} personas agree"
            )
        else:
            discourse.append(f"judge {key}: kept ({', '.join(personas)})")
        merged.append(chosen)

    if not order:
        discourse.append("debate: no persona findings to judge")
    return {
        "findings": merged,
        "discourse": discourse,
        "dropped": dropped,
        "votes": votes,
        "personas": list(PERSONAS),
    }


def run_debate_review(
    client: Any,
    prompt: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> tuple[str, list[Finding], str]:
    """Run one LLM pass per persona, then judge with :func:`run_debate`.

    Returns ``(summary, findings, provider)`` mirroring
    :func:`quality_gates.review.llm.run_llm_review`. When ``client`` is
    ``None`` or every persona call fails, falls back to a single generic pass
    (and finally to ``("heuristic", [])``) so debate mode never breaks the
    review gate. Only uses ``client.complete`` plus local parsing — no new
    dependencies, no edits to ``llm.py``.
    """
    from quality_gates.review.parse import findings_from_payload, parse_json_object

    try:
        from quality_gates.review.llm import SUBMIT_SCHEMA as _schema
        from quality_gates.review.llm import SYSTEM as _system
        from quality_gates.review.llm import ChatTurn as _ChatTurn
    except ImportError:  # pragma: no cover - defensive, llm.py ships with the package
        return (
            "LLM debate review unavailable; heuristic findings still apply.",
            [],
            "heuristic",
        )

    if client is None:
        return ("No LLM client; heuristic findings still apply.", [], "heuristic")

    findings_by_persona: dict[str, list[Finding]] = {}
    summaries: list[str] = []
    errors: list[str] = []
    for persona in PERSONAS:
        system = f"{_system}\n\n{_PERSONA_BRIEFS[persona]}"
        user = f"{prompt}\n\nPersona: {persona}. {_schema}"
        try:
            text = client.complete(
                [_ChatTurn("system", system), _ChatTurn("user", user)],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # persona failure must not break review
            errors.append(f"{persona}: {exc}")
            continue
        parsed = parse_json_object(text)
        if not parsed:
            errors.append(f"{persona}: unparseable response")
            continue
        summary, findings = findings_from_payload(parsed)
        if summary:
            summaries.append(f"[{persona}] {summary}")
        findings_by_persona[persona] = findings

    if not findings_by_persona:
        # Fallback: single generic pass before giving up to heuristic.
        try:
            text = client.complete(
                [
                    _ChatTurn("system", _system),
                    _ChatTurn("user", prompt + "\n\n" + _schema),
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            parsed = parse_json_object(text)
            if parsed:
                summary, findings = findings_from_payload(parsed)
                return (summary, findings, "debate-fallback-single")
        except Exception as exc:  # never break the gate
            errors.append(f"fallback: {exc}")
        detail = "; ".join(errors) if errors else "no persona findings"
        return (
            f"LLM debate review failed ({detail}); heuristic findings still apply.",
            [],
            "heuristic",
        )

    verdict = run_debate(findings_by_persona)
    summary = (
        " ".join(summaries)
        if summaries
        else f"Debate review ({', '.join(findings_by_persona)})."
    )
    if verdict["discourse"]:
        summary += "\n\nDiscourse:\n" + "\n".join(
            f"- {line}" for line in verdict["discourse"]
        )
    return (summary, verdict["findings"], "debate")
