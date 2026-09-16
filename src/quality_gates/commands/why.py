"""``codesheriff why`` — explain a finding without re-running the gates.

The review's top ease-of-use complaint: a finding id appears in CI, and the
developer has no local way to ask *why* it fired, *what* it saw, and *what the
smallest safe fix is*. ``why`` reads the last-run artifact so the answer costs
no compute.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quality_gates.findings_artifact import load_last_findings
from quality_gates.ignore import find_suppression_rule
from quality_gates.models import Finding
from quality_gates.review.explain import explain_finding


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "why",
        help="explain a finding from the last run (no re-scan)",
    )
    parser.add_argument("finding_id", nargs="?", help="finding id from a report")
    parser.add_argument(
        "--rule", default=None, help="explain every last-run finding of this rule"
    )
    parser.add_argument("--path", default=None, help="narrow to a file path")
    parser.add_argument("--json", action="store_true")


def handle(args: argparse.Namespace, root: Path, config) -> int | None:
    if getattr(args, "command", None) != "why":
        return None
    rows = load_last_findings(root)
    if not rows:
        print("no last-run findings; run `codesheriff review` first")
        return 2
    matches = _select(rows, args)
    if not matches:
        print(_not_found(args))
        return 1
    if args.json:
        print(json.dumps([_payload(root, row) for row in matches], indent=2))
        return 0
    for index, row in enumerate(matches):
        if index:
            print()
        print(_render(root, row))
    return 0


def _select(rows: list[dict], args: argparse.Namespace) -> list[dict]:
    if getattr(args, "finding_id", None):
        wanted = args.finding_id
        return [row for row in rows if str(row.get("fingerprint") or "") == wanted]
    out = rows
    if args.rule:
        out = [row for row in out if str(row.get("rule") or "") == args.rule]
    if args.path:
        out = [row for row in out if args.path in str(row.get("path") or "")]
    return out[:20]


def _not_found(args: argparse.Namespace) -> str:
    if getattr(args, "finding_id", None):
        return (
            f"finding {args.finding_id} is not in .quality-reports/findings-last.json; "
            "it may be from an older run. Try `codesheriff why --rule <name>`."
        )
    return "no matching findings in the last run"


def _payload(root: Path, row: dict) -> dict[str, object]:
    finding_id = str(row.get("fingerprint") or "")
    rule = find_suppression_rule(root, finding_id)
    return {
        **row,
        "suppressed": rule is not None,
        "suppression_reason": rule.reason if rule else None,
    }


def _render(root: Path, row: dict) -> str:
    finding_id = str(row.get("fingerprint") or "")
    lines = [
        f"{row.get('severity') or 'warning'} · {row.get('gate') or 'review'} · "
        f"{row.get('rule') or 'review'}",
        f"where: {row.get('path') or '?'}:{row.get('line') or '?'}",
    ]
    if row.get("snippet"):
        lines.append(f"code: {row['snippet']}")
    lines.append(f"what: {row.get('message') or ''}")
    lines.append("")
    lines.append(explain_finding(_finding_from_row(row)))
    rule = find_suppression_rule(root, finding_id)
    if rule is not None:
        lines.append("")
        lines.append(
            f"status: suppressed ({rule.reason or 'accepted'}) — "
            f"it will not block the merge"
        )
    else:
        lines.append("")
        lines.append(
            f"accept it: `codesheriff suppress {finding_id} --owner <you> "
            '--reason "<why>"`'
        )
    return "\n".join(lines)


def _finding_from_row(row: dict) -> Finding:
    return Finding(
        gate=str(row.get("gate") or "review"),
        message=str(row.get("message") or ""),
        path=str(row.get("path") or "") or None,
        line=row.get("line") if isinstance(row.get("line"), int) else None,
        rule=str(row.get("rule") or "") or None,
        snippet=str(row.get("snippet") or "") or None,
        severity=str(row.get("severity") or "warning"),
    )


__all__ = ["handle", "register"]
