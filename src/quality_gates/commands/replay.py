"""``codesheriff replay`` — re-emit a historical run from ``history.json``.

Audit and compliance need "show me exactly what Sheriff said on run-0007 and
why the merge was allowed". Previously the only artifact was the mutable
``.quality-reports/quality-report.json``, so a later run overwrote the evidence.
``replay`` reads the append-only history and reprints the report and the
certificate that accompanied it — no gates re-run, no network, deterministic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from quality_gates.certificate import render_certificate
from quality_gates.report import load_history


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "replay",
        help="re-emit a historical run's report and certificate (audit trail)",
    )
    parser.add_argument(
        "run_id", nargs="?", help="run id from `codesheriff replay` (e.g. run-0007)"
    )
    parser.add_argument(
        "--last", action="store_true", help="replay the most recent run"
    )
    parser.add_argument(
        "--list", action="store_true", help="list retained runs and exit"
    )
    parser.add_argument("--json", action="store_true")


def handle(args: argparse.Namespace, root: Path, config) -> int | None:
    if getattr(args, "command", None) != "replay":
        return None
    entries = load_history(root / ".quality-reports")
    if not entries:
        print("no run history yet; run `codesheriff run` first")
        return 2
    if args.list:
        return _list(entries, as_json=args.json)
    entry = _select(entries, args)
    if entry is None:
        print(
            f"run {args.run_id!r} is not in history (retained: {_ids(entries)}); "
            "use `codesheriff replay --list`"
        )
        return 1
    return _emit(entry, as_json=args.json)


def _ids(entries: list[dict[str, Any]]) -> str:
    return ", ".join(str(item.get("run_id") or "?") for item in entries)


def _list(entries: list[dict[str, Any]], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(entries, indent=2))
        return 0
    print(f"{len(entries)} retained run(s) in .quality-reports/history.json")
    for entry in entries:
        certificate = entry.get("certificate") or {}
        state = certificate.get("state") or (
            "ready" if certificate.get("ready") else "-"
        )
        print(
            f"  {entry.get('run_id') or '?':<10} {entry.get('ts') or '?'} "
            f"{entry.get('verdict') or '?'!s:<5} "
            f"errors={entry.get('errors')} warnings={entry.get('warnings')} "
            f"certificate={state}"
        )
    return 0


def _select(
    entries: list[dict[str, Any]], args: argparse.Namespace
) -> dict[str, Any] | None:
    if getattr(args, "last", False) or not getattr(args, "run_id", None):
        return entries[-1]
    wanted = str(args.run_id)
    for entry in reversed(entries):
        if str(entry.get("run_id") or "") == wanted:
            return entry
    for entry in reversed(entries):
        if str(entry.get("ts") or "").startswith(wanted):
            return entry
    return None


def _emit(entry: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(entry, indent=2))
        return 0
    print(f"# Replay {entry.get('run_id') or '?'} ({entry.get('ts') or '?'})")
    print()
    print(f"- policy: `{entry.get('policy') or '?'}`")
    print(f"- verdict: `{entry.get('verdict') or '?'}`")
    print(f"- errors: {entry.get('errors')}  warnings: {entry.get('warnings')}")
    if entry.get("coverage") is not None:
        print(f"- coverage: {entry['coverage']}")
    failed = entry.get("failed") or []
    print(f"- failed gates: {', '.join(str(item) for item in failed) or 'none'}")
    gates = entry.get("gates") or []
    if gates:
        print(f"- gates run: {', '.join(str(item) for item in gates)}")
    certificate = entry.get("certificate")
    if isinstance(certificate, dict):
        print()
        print(render_certificate(certificate).rstrip())
    else:
        print()
        print("(no certificate was recorded for this run)")
    return 0


__all__ = ["handle", "register"]
