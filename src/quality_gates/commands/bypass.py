"""``codesheriff bypass`` — emergency break-glass PR bypass with mandatory audit trail.

Allows developers to ship emergency hotfixes without getting blocked by non-P0 gates,
recording an auditable compliance justification in `.quality-reports/bypass.json`.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig


def record_bypass(
    root: Path,
    *,
    reason: str,
    author: str = "",
    pr: str = "",
) -> dict[str, Any]:
    """Record an emergency bypass in the project audit records."""
    reports_dir = root / ".quality-reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    bypass_file = reports_dir / "bypass.json"

    entry: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "reason": reason,
        "author": author
        or os.environ.get("GITHUB_ACTOR")
        or os.environ.get("USER")
        or "unknown",
        "pr": pr or os.environ.get("GITHUB_REF") or "",
        "status": "active_emergency_bypass",
    }

    bypasses: list[dict[str, Any]] = []
    if bypass_file.is_file():
        try:
            data = json.loads(bypass_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                bypasses = data
        except (OSError, json.JSONDecodeError):
            pass

    bypasses.append(entry)
    bypass_file.write_text(json.dumps(bypasses, indent=2) + "\n", encoding="utf-8")
    return entry


def is_bypass_active(root: Path) -> bool:
    """Check if emergency bypass is enabled via environment variable, commit, or bypass record."""
    if os.environ.get("SHERIFF_BYPASS") in {"1", "true", "yes"}:
        return True
    bypass_file = root / ".quality-reports" / "bypass.json"
    if bypass_file.is_file():
        try:
            data = json.loads(bypass_file.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return True
        except (OSError, json.JSONDecodeError):
            return False
    return False


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "bypass",
        help="log an emergency bypass justification to unblock critical production hotfixes",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="business or incident justification for emergency bypass",
    )
    parser.add_argument("--author", default="", help="engineer authorizing the bypass")
    parser.add_argument("--pr", default="", help="pull request number or reference")
    parser.add_argument(
        "--json", action="store_true", help="output bypass event in JSON"
    )


def handle(args: argparse.Namespace, root: Path, config: QualityConfig) -> int | None:
    if getattr(args, "command", None) != "bypass":
        return None

    entry = record_bypass(
        root=root,
        reason=args.reason,
        author=args.author,
        pr=args.pr,
    )

    if args.json:
        print(json.dumps(entry, indent=2))
        return 0

    print("⚠️  EMERGENCY BYPASS RECORDED")
    print(f"Timestamp: {entry['timestamp']}")
    print(f"Author:    {entry['author']}")
    print(f"Reason:    {entry['reason']}")
    print("Non-critical quality gate enforcement waived for this emergency run.")
    return 0


__all__ = ["handle", "is_bypass_active", "record_bypass", "register"]
