"""Comment reactions and disposition learning (non-security rules only)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quality_gates.models import Finding
from quality_gates.review.parse import fingerprint

FEEDBACK_FILE = "feedback.json"
COMMITTED_FEEDBACK_FILE = ".sheriff/feedback.json"
LEGACY_FEEDBACK_FILE = ".quality/feedback.json"
REACTION_MAP = {
    "+1": "useful",
    "heart": "useful",
    "-1": "not_useful",
    "confused": "incorrect",
    "eyes": "needs_context",
}

_SECURITY = {
    "eval",
    "secret",
    "gitleaks",
    "sql-concat",
    "innerhtml",
    "pickle",
    "shell-true",
    "hardcoded-secret",
}


def classify_reaction(content: str) -> str | None:
    return REACTION_MAP.get((content or "").strip().lower())


def _paths(root: Path) -> list[Path]:
    return [
        root / COMMITTED_FEEDBACK_FILE,
        root / LEGACY_FEEDBACK_FILE,
        root / ".quality-reports" / FEEDBACK_FILE,
    ]


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_feedback(root: Path) -> dict[str, Any]:
    """Merge the committed store with the local cache (committed values win)."""
    merged: dict[str, Any] = {"rules": {}, "events": []}
    for path in _paths(root):
        data = _read(path)
        rules = data.get("rules") if isinstance(data.get("rules"), dict) else {}
        for rule, bucket in rules.items():
            if not isinstance(bucket, dict):
                continue
            target = merged["rules"].setdefault(
                rule, {"useful": 0, "not_useful": 0, "incorrect": 0}
            )
            for key in ("useful", "not_useful", "incorrect"):
                target[key] = max(int(target.get(key) or 0), int(bucket.get(key) or 0))
        events = data.get("events")
        if isinstance(events, list):
            merged["events"].extend(events)
    return merged


def record_feedback(
    root: Path,
    *,
    rule: str,
    disposition: str,
    reason: str = "",
    path: str | None = None,
) -> dict[str, Any]:
    event = {
        "rule": rule,
        "disposition": disposition,
        "reason": reason,
        "path": path,
    }
    for dest in _paths(root):
        data = _read(dest)
        rules = data.setdefault("rules", {})
        bucket = rules.setdefault(rule, {"useful": 0, "not_useful": 0, "incorrect": 0})
        if disposition in bucket:
            bucket[disposition] = int(bucket.get(disposition) or 0) + 1
        data.setdefault("events", []).append(event)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return event


def should_suppress_rule(root: Path, rule: str | None) -> bool:
    if not rule or _is_security(rule):
        return False
    bucket = (load_feedback(root).get("rules") or {}).get(rule) or {}
    useful = int(bucket.get("useful") or 0)
    noise = int(bucket.get("not_useful") or 0) + int(bucket.get("incorrect") or 0)
    return noise >= 3 and noise > useful * 2


def apply_feedback(root: Path, findings: list[Finding]) -> list[Finding]:
    kept = []
    for item in findings:
        if should_suppress_rule(root, item.rule):
            continue
        kept.append(item)
    return kept


def ingest_reactions(root: Path, reactions: list[dict[str, Any]]) -> int:
    count = 0
    for item in reactions:
        disposition = classify_reaction(str(item.get("content") or ""))
        rule = str(item.get("rule") or "")
        if not disposition or not rule:
            continue
        record_feedback(
            root,
            rule=rule,
            disposition=disposition,
            reason=str(item.get("reason") or ""),
        )
        count += 1
    return count


def finding_key(item: Finding) -> str:
    return fingerprint(item, bucket=1)


def _is_security(rule: str) -> bool:
    lowered = rule.lower()
    return any(token in lowered for token in _SECURITY)
