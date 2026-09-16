"""``codesheriff suppress`` — durable, auditable false-positive suppression.

Turns a specific finding into a committed, expiring ``[[ignore]]`` record so
accepted noise stops re-appearing on every PR without waiving the whole rule.
``audit`` reports expired and orphaned suppressions so they get cleaned up.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from quality_gates.findings_artifact import load_last_findings
from quality_gates.ignore import (
    IgnoreRule,
    anchor_for,
    append_ignore,
    find_suppression_rule,
    ignore_path,
    load_ignore_rules,
    remove_suppression,
)
from quality_gates.models import Finding


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "suppress",
        help="suppress a specific finding so it stops re-appearing",
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="add",
        choices=["add", "audit", "list", "remove"],
        help="add a suppression (default), audit existing ones, list, or remove",
    )
    parser.add_argument("finding_id", nargs="?", help="finding id from a report")
    parser.add_argument("--reason", default="accepted false positive")
    parser.add_argument("--owner", default="")
    parser.add_argument(
        "--days", type=int, default=90, help="expiry in days (0 = never)"
    )
    parser.add_argument("--rule", default=None)
    parser.add_argument("--path", default=None)
    parser.add_argument("--gate", default=None)
    parser.add_argument("--json", action="store_true")


def handle(args: argparse.Namespace, root: Path, config) -> int | None:
    if getattr(args, "command", None) != "suppress":
        return None
    action = getattr(args, "action", "add")
    if action in {"add", "remove"} and not getattr(args, "finding_id", None):
        _print_findings(root, args)
        return 2
    if action == "add":
        return _add(args, root)
    if action == "remove":
        return _remove(args, root)
    if action == "list":
        return _list(args, root)
    return _audit(args, root)


def _add(args: argparse.Namespace, root: Path) -> int:
    finding_id = args.finding_id
    row = _resolve_finding(root, finding_id)
    if row is None:
        print(f"finding {finding_id} not found in .quality-reports/findings-last.json")
        print("run `codesheriff review --json` first, or pass --rule/--path")
        return 2
    already = find_suppression_rule(root, finding_id)
    if already is not None:
        print(f"already suppressed: {already.reason or 'accepted'}")
        return 0
    days = None if args.days == 0 else args.days
    anchor = anchor_for(_finding_from_row(root, row), root)
    dest = append_ignore(
        root,
        rule=str(row.get("rule") or args.rule or "*"),
        path=str(row.get("path") or args.path or "") or None,
        gate=str(row.get("gate") or args.gate or "") or None,
        reason=args.reason,
        owner=args.owner,
        days=days,
        fingerprint=finding_id,
        anchor=anchor,
    )
    print(f"suppressed {finding_id} -> {dest.relative_to(root)}")
    if anchor:
        print(
            "anchor recorded: the waiver survives line drift as long as the "
            "flagged code itself is unchanged"
        )
    if not args.owner:
        print("tip: pass --owner your-handle so the waiver has an accountable owner")
    return 0


def _finding_from_row(root: Path, row: dict) -> Finding:
    return Finding(
        gate=str(row.get("gate") or "review"),
        message=str(row.get("message") or ""),
        path=str(row.get("path") or "") or None,
        line=row.get("line") if isinstance(row.get("line"), int) else None,
        rule=str(row.get("rule") or "") or None,
        snippet=str(row.get("snippet") or "") or None,
    )


def _remove(args: argparse.Namespace, root: Path) -> int:
    if remove_suppression(root, args.finding_id):
        print(f"removed suppression for {args.finding_id}")
        return 0
    print(f"no suppression found for {args.finding_id}")
    return 1


def _list(args: argparse.Namespace, root: Path) -> int:
    rules = load_ignore_rules(root, include_expired=True)
    payload = [_rule_dict(rule) for rule in rules]
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{len(payload)} suppression rule(s) in {ignore_path(root).name}")
        for item in payload:
            scope = item["fingerprint"] or item["rule"] or "*"
            state = "active" if item["active"] else "expired"
            print(f"  [{state}] {scope} {item['reason']}")
    return 0


def _audit(args: argparse.Namespace, root: Path) -> int:
    rules = load_ignore_rules(root, include_expired=True)
    rows = load_last_findings(root)
    current = {str(row.get("fingerprint") or "") for row in rows}
    current_anchors = {
        anchor
        for row in rows
        if (anchor := anchor_for(_finding_from_row(root, row), root))
    }
    # Orphaned = an identity waiver whose finding no longer appears (by exact
    # fingerprint or by content anchor); the code was fixed or moved, so the
    # suppression is dead weight worth pruning.
    stale = current if rows else set()
    stale_anchors = current_anchors if rows else set()
    now = datetime.now(UTC)
    report: dict[str, object] = {
        "active": 0,
        "expired": 0,
        "expiring": 0,
        "orphaned": 0,
        "drifted": 0,
        "items": [],
    }
    items: list[dict[str, object]] = []
    for rule in rules:
        state = _state(rule, now)
        orphaned = False
        drifted = False
        if rule.fingerprint or rule.anchor:
            exact = bool(rule.fingerprint) and rule.fingerprint in stale
            anchored = bool(rule.anchor) and rule.anchor in stale_anchors
            orphaned = not (exact or anchored)
            drifted = anchored and not exact
        entry = _rule_dict(rule)
        entry["state"] = state
        entry["orphaned"] = orphaned
        entry["drifted"] = drifted
        if state == "expired":
            report["expired"] = int(report["expired"]) + 1
        else:
            report["active"] = int(report["active"]) + 1
        if state == "expiring":
            report["expiring"] = int(report["expiring"]) + 1
        if orphaned:
            report["orphaned"] = int(report["orphaned"]) + 1
        if drifted:
            report["drifted"] = int(report["drifted"]) + 1
        items.append(entry)
    report["items"] = items
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(
        f"suppressions: {report['active']} active, {report['expired']} expired, "
        f"{report['expiring']} expiring soon, {report['orphaned']} orphaned"
    )
    for entry in items:
        flags = [str(entry["state"])]
        if entry["orphaned"]:
            flags.append("orphaned")
        if entry["drifted"]:
            flags.append("held-through-drift")
        scope = entry["fingerprint"] or entry["rule"] or "*"
        print(f"  [{'+'.join(flags)}] {scope} — {entry['reason']}")
    if report["drifted"]:
        print(
            f"{report['drifted']} waiver(s) still match after line drift — "
            "no re-triage needed"
        )
    if report["expired"] or report["orphaned"]:
        print("prune with `codesheriff suppress remove <finding-id>`")
    return 0


def _state(rule: IgnoreRule, now: datetime) -> str:
    if not rule.expires:
        return "active"
    try:
        expires = datetime.fromisoformat(rule.expires.replace("Z", "+00:00"))
    except ValueError:
        return "expired"
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    days = (expires - now).days
    if days < 0:
        return "expired"
    if days <= 14:
        return "expiring"
    return "active"


def _rule_dict(rule: IgnoreRule) -> dict[str, object]:
    return {
        "fingerprint": rule.fingerprint,
        "anchor": rule.anchor,
        "rule": rule.rule,
        "gate": rule.gate,
        "path": rule.path,
        "reason": rule.reason,
        "owner": rule.owner,
        "expires": rule.expires,
        "active": rule.active(),
    }


def _resolve_finding(root: Path, finding_id: str) -> dict | None:
    for row in load_last_findings(root):
        if str(row.get("fingerprint") or "") == finding_id:
            return row
    return None


def _print_findings(root: Path, args: argparse.Namespace) -> None:
    rows = load_last_findings(root)
    if not rows:
        print("no last-run findings; run a check first", flush=True)
        return
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    print(f"{len(rows)} finding(s); pass an id to `codesheriff suppress <id>`:")
    for row in rows[:50]:
        print(
            f"  {row.get('fingerprint')}  "
            f"{row.get('path')}:{row.get('line')}  {row.get('message')}"
        )


__all__ = ["handle", "register"]
