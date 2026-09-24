"""codesheriff status — quick project health overview."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.oracle import remaining_from_reports


def register(sub: object) -> None:

    parser = sub.add_parser(
        "status",
        help="quick project health: gate verdicts, blockers, agent loop state",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="show full details"
    )
    parser.add_argument("--watch", action="store_true", help="watch mode status")


def handle(args: object, root: Path, config) -> int | None:
    if getattr(args, "command", None) != "status":
        return None

    as_json = getattr(args, "json", False)
    verbose = getattr(args, "verbose", False)

    payload = remaining_from_reports(root)

    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        _render_console(payload, verbose)

    green = payload.get("green") is True
    return 0 if green else 1


def _render_console(payload: dict, verbose: bool) -> None:
    green = payload.get("green")
    certificate = payload.get("certificate") or {}
    playbook = payload.get("playbook") or {}
    nxt = playbook.get("next") or {}
    blocking = payload.get("blocking") or []
    warnings = payload.get("warnings") or []
    gates = payload.get("gates") or []

    status = "GREEN" if green else "RED"
    print(f"Status: {status}")
    print(f"Certificate ready: {certificate.get('ready', False)}")
    if certificate.get("auto_merge") == "ready":
        print("Auto-merge: ready")
    print()

    gate_rows = [g for g in gates if g.get("error_count", 0) > 0]
    if gate_rows:
        print("Failing gates:")
        for g in gate_rows:
            print(f"  {g['name']}: {g['error_count']} error(s)")
    elif not gate_rows and not blocking:
        print("All gates passing ✓")
    print()

    if blocking:
        print(f"Blocking findings ({len(blocking)}):")
        for item in blocking[:20]:
            loc = item.get("path") or item.get("location") or "repo"
            if item.get("line") and ":" not in str(loc):
                loc = f"{loc}:{item['line']}"
            print(
                f"  [{item.get('gate')}/{item.get('rule')}] {loc}: {item.get('message')}"
            )
            if item.get("autofix"):
                print(f"    Fix: {item['autofix']}")
        print()

    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for item in warnings[:10]:
            loc = item.get("path") or item.get("location") or "repo"
            print(f"  [{item.get('gate')}] {loc}: {item.get('message')}")
        print()

    if nxt.get("instruction"):
        print(f"Next action: {nxt['instruction']}")
    if playbook.get("autofix_first"):
        print("Auto-fix first:")
        for step in playbook["autofix_first"]:
            print(f"  {step.get('command')} ({step.get('gate')})")
    print()

    if certificate.get("state"):
        print(f"State: {certificate['state']}")
    if payload.get("needs_human"):
        print("⚠  Oracle stalled — human intervention required")
        print("   Run: codesheriff oracle --reset-stall")

    if verbose:
        print("\nFull details:")
        print(json.dumps(payload, indent=2))


def status_payload(root: Path) -> dict:
    """Return the status payload without printing. Useful for agents."""
    return remaining_from_reports(root)
