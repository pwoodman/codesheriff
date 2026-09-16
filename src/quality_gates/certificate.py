"""Merge certificate: the signal that auto-merge is safe."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quality_gates import __version__
from quality_gates.playbook import build_playbook


def build_certificate(
    payload: dict[str, Any], *, root: Path | None = None
) -> dict[str, Any]:
    """Machine-readable merge readiness. Ready only when the oracle is green."""
    playbook = payload.get("playbook") or build_playbook(payload)
    green = bool(payload.get("green"))
    review_errors = [
        item
        for item in (payload.get("review") or {}).get("findings") or []
        if isinstance(item, dict) and item.get("severity") == "error"
    ]
    comments = list(payload.get("comments") or [])
    remaining = int(playbook.get("remaining") or 0)
    needs_human = bool(payload.get("needs_human"))
    ready = (
        green
        and remaining == 0
        and not review_errors
        and not comments
        and not needs_human
    )
    state = _state(
        green=green,
        ready=ready,
        remaining=remaining,
        review_errors=review_errors,
        comments=comments,
        needs_human=needs_human,
    )
    snapshot = ""
    if root is not None:
        try:
            from quality_gates.evidence import snapshot_digest

            snapshot = snapshot_digest(root)
        except (OSError, ValueError, RuntimeError):
            snapshot = ""
    return {
        "ready": ready,
        "state": state,
        "needs_human": needs_human,
        "auto_merge": "ready" if ready else "blocked",
        "reason": _reason(state),
        "version": __version__,
        "issued_at": datetime.now(UTC).isoformat(),
        "snapshot": snapshot or None,
        "blocking": [item.get("gate") for item in playbook.get("steps") or []],
        "missing_required": list(payload.get("missing_required") or []),
        "next": (playbook.get("next") or {}).get("command"),
    }


def _state(
    *,
    green: bool,
    ready: bool,
    remaining: int,
    review_errors: list[Any],
    comments: list[Any],
    needs_human: bool,
) -> str:
    """Coarse lifecycle status, so callers do not have to infer it from flags."""
    if ready:
        return "ready"
    if needs_human:
        return "needs-human"
    if not green and remaining == 0 and not review_errors and not comments:
        return "awaiting-review"
    return "work-remaining"


def _reason(state: str) -> str:
    if state == "ready":
        return (
            "All required gates passed, review errors are clear, and no "
            "unresolved PR threads remain."
        )
    if state == "awaiting-review":
        return (
            "No mechanical work remains, but the review gate has not produced a "
            "clean verdict yet. Wait for the reviewer, then re-run the oracle."
        )
    if state == "needs-human":
        return (
            "The oracle repeated the same next action without progress; a human "
            "decision is required before it can go green."
        )
    return (
        "Blocking findings, missing required results, or unresolved review "
        "threads remain."
    )


def write_certificate(
    root: Path, payload: dict[str, Any], *, key: str | None = None
) -> Path:
    certificate = payload.get("certificate")
    if not isinstance(certificate, dict):
        certificate = build_certificate(payload, root=root)
        payload["certificate"] = certificate
    if key:
        certificate = sign_certificate(certificate, key)
        payload["certificate"] = certificate
    directory = root / ".quality-reports"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "certificate.json"
    path.write_text(json.dumps(certificate, indent=2) + "\n", encoding="utf-8")
    (directory / "certificate.md").write_text(
        render_certificate(certificate), encoding="utf-8"
    )
    return path


def sign_certificate(certificate: dict[str, Any], key: str) -> dict[str, Any]:
    """Attach an HMAC-SHA256 signature so a certificate is verifiable off-machine."""
    if not key:
        raise ValueError("signing key must not be empty")
    body = {name: value for name, value in certificate.items() if name != "signature"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    return {**body, "signature": {"algorithm": "hmac-sha256", "value": signature}}


def verify_certificate(certificate: dict[str, Any], key: str) -> bool:
    """True when the embedded signature matches the certificate body."""
    signature = certificate.get("signature")
    if not isinstance(signature, dict):
        return False
    expected = sign_certificate(certificate, key).get("signature")
    value = str(signature.get("value") or "")
    provided = str((expected or {}).get("value") or "")
    return bool(value) and hmac.compare_digest(value, provided)


def render_certificate(certificate: dict[str, Any]) -> str:
    status = "READY" if certificate.get("ready") else "BLOCKED"
    lines = [
        f"# Merge certificate: {status}",
        "",
        f"- auto_merge: `{certificate.get('auto_merge')}`",
        f"- reason: {certificate.get('reason')}",
        f"- sheriff: {certificate.get('version')}",
        f"- issued: {certificate.get('issued_at')}",
    ]
    if certificate.get("snapshot"):
        lines.append(f"- snapshot: `{certificate['snapshot']}`")
    blocking = certificate.get("blocking") or []
    if blocking:
        lines.append("- remaining gates: " + ", ".join(str(item) for item in blocking))
    if certificate.get("next") and not certificate.get("ready"):
        lines.append(f"- next: `{certificate['next']}`")
    lines.append("")
    if certificate.get("ready"):
        lines.append(
            "GitHub: enable auto-merge on the pull request. If **The Code Sheriff** "
            "is a required check, the PR can land without a human re-review of the diff."
        )
    else:
        lines.append(
            "Do not auto-merge. Run `codesheriff oracle --run --prompt` and fix."
        )
    lines.append("")
    return "\n".join(lines)
