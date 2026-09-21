"""Thumbs up/down learning for review findings (P2).

Reads ``.quality-reports/thumbs.json`` — a ``{fingerprint: +1/-1}`` map where
keys are :func:`quality_gates.review.parse.fingerprint` values — and applies a
confidence boost (``+1``) or penalty (``-1``) to matching findings.

Wiring into ``codesheriff review --learn`` (``src/quality_gates/cli.py``,
P0-owned) is a two-liner, intentionally *not* applied here to avoid
conflicts::

    review.add_argument("--learn", action="store_true",
                        help="apply .quality-reports/thumbs.json feedback")
    ...
    if args.command == "review":
        if args.learn:
            from quality_gates.review.learning import review_learn_hook
            review_learn_hook(root)

Until then the hook is callable directly and via
``python -m quality_gates.review.learning --learn``. All functions are
import-safe (stdlib only) and never raise on missing/malformed input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from quality_gates.models import Finding
from quality_gates.review.parse import fingerprint

THUMBS_NAME = "thumbs.json"
REVIEW_NAME = "review.json"

BOOST = 0.15
PENALTY = 0.20
BASELINE_CONFIDENCE = 0.5

_TEXT_CONFIDENCE = {"high": 0.9, "medium": 0.6, "low": 0.3}


def default_thumbs_path(root: Path | str | None = None) -> Path:
    """Return ``<root>/.quality-reports/thumbs.json`` (``root`` = cwd)."""
    base = Path(root) if root is not None else Path.cwd()
    return base / ".quality-reports" / THUMBS_NAME


def load_thumbs(path: Path | str | None = None) -> dict[str, int]:
    """Load ``{fingerprint: +1/-1}`` feedback; ``{}`` when absent/invalid.

    Positive values normalise to ``+1``, negative to ``-1``; zero,
    non-numeric, and empty-key entries are ignored. Never raises.
    """
    target = Path(path) if path is not None else default_thumbs_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, int] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            out[key.strip()] = 1
        elif number < 0:
            out[key.strip()] = -1
    return out


def _confidence_value(finding: Finding) -> float:
    """Numeric confidence as a float, robust to ``str | float | None``.

    ``Finding.confidence`` is ``str | None`` on this base but the P0 track
    moves it to ``float`` (default 0.5, with coercion); this helper accepts
    floats, numeric strings, and HIGH/MEDIUM/LOW labels, falling back to
    ``BASELINE_CONFIDENCE`` when no usable signal is present.
    """
    value = finding.confidence
    if isinstance(value, bool):
        return BASELINE_CONFIDENCE
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if value is None:
        return BASELINE_CONFIDENCE
    text = str(value).strip().lower()
    if not text:
        return BASELINE_CONFIDENCE
    try:
        return max(0.0, min(1.0, float(text)))
    except (TypeError, ValueError):
        return _TEXT_CONFIDENCE.get(text, BASELINE_CONFIDENCE)


def _conf(finding: Finding) -> float:
    """Alias for :func:`_confidence_value` (P0-track ``float`` robustness)."""
    return _confidence_value(finding)


def _finding_keys(finding: Finding) -> list[str]:
    return [fingerprint(finding, bucket=1), fingerprint(finding, bucket=5)]


def apply_feedback(
    findings: list[Finding],
    thumbs: dict[str, int],
    *,
    boost: float = BOOST,
    penalty: float = PENALTY,
) -> list[Finding]:
    """Apply ``+1`` boost / ``-1`` penalty to finding confidence in place.

    A finding matches when any of its fingerprints (exact line, then
    bucketed) appears in ``thumbs``. Confidence is stored back as a float
    rounded to two decimals and clamped to ``[0, 1]`` (matching
    ``Finding.confidence``). Returns the same list.
    """
    if not thumbs:
        return findings
    for item in findings:
        vote = 0
        for key in _finding_keys(item):
            if key in thumbs:
                vote = thumbs[key]
                break
        if vote == 0:
            continue
        current = _conf(item)
        updated = current + boost if vote > 0 else current - penalty
        item.confidence = round(max(0.0, min(1.0, updated)), 2)
    return findings


def review_learn_hook(
    root: Path | str | None = None,
    *,
    thumbs_path: Path | str | None = None,
    review_path: Path | str | None = None,
    findings: list[Finding] | None = None,
) -> dict[str, Any]:
    """Apply thumbs feedback to the last review; the ``--learn`` hook body.

    When ``findings`` is given, adjust them in memory and report counts.
    Otherwise load ``.quality-reports/review.json`` findings, apply feedback,
    and write the file back (confidence fields only). Always reads the thumbs
    file when present; returns ``{"applied": ..., "boosted": ...,
    "penalized": ..., "thumbs": ...}`` and never raises.
    """
    base = Path(root) if root is not None else Path.cwd()
    thumbs = load_thumbs(
        Path(thumbs_path) if thumbs_path else default_thumbs_path(base)
    )
    if not thumbs:
        return {
            "applied": 0,
            "boosted": 0,
            "penalized": 0,
            "thumbs": 0,
            "note": "no thumbs file",
        }

    if findings is not None:
        before = [_conf(item) for item in findings]
        apply_feedback(findings, thumbs)
        boosted = sum(
            1 for item, old in zip(findings, before, strict=True) if _conf(item) > old
        )
        penalized = sum(
            1 for item, old in zip(findings, before, strict=True) if _conf(item) < old
        )
        return {
            "applied": boosted + penalized,
            "boosted": boosted,
            "penalized": penalized,
            "thumbs": len(thumbs),
        }

    target = (
        Path(review_path) if review_path else base / ".quality-reports" / REVIEW_NAME
    )
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "applied": 0,
            "boosted": 0,
            "penalized": 0,
            "thumbs": len(thumbs),
            "note": "no review.json to learn on",
        }
    rows = payload.get("findings")
    if not isinstance(rows, list):
        return {
            "applied": 0,
            "boosted": 0,
            "penalized": 0,
            "thumbs": len(thumbs),
            "note": "no findings in review.json",
        }
    boosted = penalized = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        probe = Finding(
            gate=str(row.get("gate") or "review"),
            message=str(row.get("message") or ""),
            path=row.get("path"),
            line=row.get("line") if isinstance(row.get("line"), int) else None,
            rule=row.get("rule"),
            confidence=row.get("confidence"),
        )
        vote = 0
        for key in _finding_keys(probe):
            if key in thumbs:
                vote = thumbs[key]
                break
        if vote == 0:
            continue
        old = _conf(probe)
        probe.confidence = None  # reset so apply path below recomputes cleanly
        current = old
        updated = current + BOOST if vote > 0 else current - PENALTY
        row["confidence"] = round(max(0.0, min(1.0, updated)), 2)
        if vote > 0:
            boosted += 1
        else:
            penalized += 1
    try:
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return {
            "applied": 0,
            "boosted": 0,
            "penalized": 0,
            "thumbs": len(thumbs),
            "note": "could not write review.json",
        }
    return {
        "applied": boosted + penalized,
        "boosted": boosted,
        "penalized": penalized,
        "thumbs": len(thumbs),
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point: ``python -m quality_gates.review.learning --learn``."""
    parser = argparse.ArgumentParser(prog="codesheriff review --learn")
    parser.add_argument("--learn", action="store_true", help="apply thumbs feedback")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    if not args.learn:
        parser.print_help()
        return 2
    result = review_learn_hook(args.root)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
