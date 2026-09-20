"""SheriffBench: the metrics competitors do not publish.

Greptile, CodeRabbit, Cursor Bugbot, and Macroscope all report recall and
comment volume on labeled PRs. None of them publish the two numbers that
actually decide whether a review bot is tolerable in a real repo:

* **re-triage rate** — how often an already-accepted finding comes back after
  an unrelated edit shifts its line number. A bot that re-opens the same false
  positive every merge is the reason teams turn review bots off.
* **termination** — does an agent loop converge, or does it spin on the same
  blocker forever?

SheriffBench reuses the ReviewBench corpus (:mod:`quality_gates.review.bench`)
and adds precision, determinism, suppression-drift, closed-loop, and oracle
termination measurements on top of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quality_gates.diagnostics import enrich_findings
from quality_gates.ignore import IgnoreRule, anchor_for, apply_ignores
from quality_gates.models import Finding, GateResult
from quality_gates.oracle import reset_stall, track_stall
from quality_gates.review.bench import (
    BenchCase,
    _diff_from_tree,
    _new_side,
    bundled_bench_dir,
    load_cases,
    score_findings,
)
from quality_gates.review.contract import finding_payload
from quality_gates.review.heuristic import heuristic_review
from quality_gates.review.parse import fingerprint

DRIFT_PAD = (
    "# unrelated header edit\n",
    "# padding line added by another PR\n",
    "\n",
    "import os  # noqa: F401\n",
    "\n",
)


def run_sheriff_suite(
    directory: Path | None = None,
    *,
    tmp: Path | None = None,
) -> dict[str, Any]:
    """Score the heuristic engine on recall, precision, and stability."""
    root = directory or bundled_bench_dir()
    all_cases = load_cases(root)
    cases = [item for item in all_cases if item.heuristic]
    llm_only = [item.case_id for item in all_cases if not item.heuristic]
    rows: list[dict[str, Any]] = []
    for case in cases:
        findings = enrich_findings(heuristic_review(case.diff, case.languages, []))
        row = score_findings(case, findings)
        row["precision"] = _precision(case, findings)
        row["contract_missing"] = _contract_gaps(findings)
        row["deterministic"] = _deterministic(case, findings)
        rows.append(row)

    positives = [item for item in rows if item["kind"] == "positive"]
    negatives = [item for item in rows if item["kind"] == "hard_negative"]
    caught = sum(1 for item in positives if item["ok"])
    quiet = sum(1 for item in negatives if item["ok"])
    contract_clean = sum(1 for item in rows if not item["contract_missing"])
    deterministic = sum(1 for item in rows if item["deterministic"])
    precision_values = [
        item["precision"] for item in rows if item["precision"] is not None
    ]

    payload: dict[str, Any] = {
        "suite": "sheriffbench",
        "cases": len(rows),
        "positives": len(positives),
        "hard_negatives": len(negatives),
        "recall": round(caught / len(positives), 4) if positives else None,
        "hard_negative_pass": round(quiet / len(negatives), 4) if negatives else None,
        "mean_precision": (
            round(sum(precision_values) / len(precision_values), 4)
            if precision_values
            else None
        ),
        "contract_compliance": round(contract_clean / len(rows), 4) if rows else None,
        "determinism": round(deterministic / len(rows), 4) if rows else None,
        "failed": [item["id"] for item in rows if not item["ok"]],
        "heuristic_skipped": llm_only,
        "results": rows,
    }
    if tmp is not None:
        payload["retriage"] = retriage_score(tmp)
        payload["closed_loop"] = _closed_loop_rate(tmp)
        payload["termination"] = termination_score(tmp)
    return payload


def retriage_score(tmp: Path) -> dict[str, Any]:
    """How many accepted findings survive a line shift without re-triaging.

    This is the metric that separates a durable waiver from a comment that
    comes back on every merge.
    """
    work = tmp / "_retriage"
    work.mkdir(parents=True, exist_ok=True)
    cases = [
        item
        for item in load_cases()
        if item.heuristic and item.kind == "positive" and item.must_rules
    ]
    held = 0
    total = 0
    rows: list[dict[str, Any]] = []
    for case in cases:
        base = work / case.case_id
        base.mkdir(parents=True, exist_ok=True)
        target = _first_target(case)
        if target is None or not target.path:
            continue
        rel = target.path
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        original = _new_side(case.diff, rel)
        if not original.strip():
            continue
        dest.write_text(original, encoding="utf-8")

        rule = IgnoreRule(
            rule=target.rule,
            path=rel,
            reason="accepted false positive",
            owner="sheriffbench",
            fingerprint=fingerprint(target, bucket=1),
            anchor=anchor_for(target, base),
        )
        if not rule.anchor:
            continue

        shifted = "".join(DRIFT_PAD) + original
        dest.write_text(shifted, encoding="utf-8")
        after = enrich_findings(
            heuristic_review(_diff_from_tree(base, rel), case.languages, [])
        )
        result = GateResult(name="review", status="fail", findings=after)
        apply_ignores([result], base, extra=[rule])
        still = [item for item in result.findings if item.rule == target.rule]
        total += 1
        if not still:
            held += 1
        rows.append(
            {
                "case": case.case_id,
                "rule": target.rule,
                "held": not still,
            }
        )
    return {
        "cases": total,
        "held": held,
        "retriage_rate": round(1 - held / total, 4) if total else None,
        "results": rows,
    }


def termination_score(tmp: Path) -> dict[str, Any]:
    """The oracle must escalate to a human instead of looping forever."""
    state = tmp / "_termination"
    state.mkdir(parents=True, exist_ok=True)
    reset_stall(state)
    payload = {
        "green": False,
        "playbook": {"next": {"command": "codesheriff lint"}},
        "blocking": [
            {"gate": "lint", "rule": "ruff", "path": "src/app.py", "line": 10}
        ],
    }
    iterations = 0
    stalled = False
    last: dict[str, Any] = {}
    for index in range(8):
        iterations = index + 1
        last = track_stall(state, dict(payload))
        if last.get("needs_human"):
            stalled = True
            break
    reset_stall(state)
    return {
        "iterations_to_stall": iterations,
        "stalled": stalled,
        "repeats": (last.get("stall") or {}).get("repeats"),
    }


def render_sheriff_scorecard(payload: dict[str, Any]) -> str:
    lines = ["# SheriffBench scorecard", ""]
    lines += [
        "| metric | value |",
        "| --- | --- |",
        f"| recall | {payload.get('recall')} |",
        f"| hard-negative pass (precision proxy) | {payload.get('hard_negative_pass')} |",
        f"| mean precision | {payload.get('mean_precision')} |",
        f"| finding contract compliance | {payload.get('contract_compliance')} |",
        f"| determinism | {payload.get('determinism')} |",
    ]
    retriage = payload.get("retriage")
    if isinstance(retriage, dict):
        lines.append(
            f"| suppression re-triage rate (lower is better) | "
            f"{retriage.get('retriage_rate')} |"
        )
    closed_loop = payload.get("closed_loop")
    if isinstance(closed_loop, dict):
        lines.append(
            f"| closed-loop resolution | {closed_loop.get('resolution_rate')} |"
        )
    termination = payload.get("termination")
    if isinstance(termination, dict):
        lines.append(
            f"| oracle stalls at iteration | {termination.get('iterations_to_stall')} |"
        )
    failed = payload.get("failed") or []
    lines += ["", f"- failed cases: {', '.join(failed) or 'none'}"]
    skipped = payload.get("heuristic_skipped") or []
    if skipped:
        lines.append(
            f"- heuristic-skipped (LLM-only): {', '.join(str(item) for item in skipped)}"
        )
    lines.append("")
    return "\n".join(lines)


def write_sheriff_scorecard(root: Path, payload: dict[str, Any]) -> Path:
    dest = root / ".quality-reports" / "eval" / "SHERIFFBENCH.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (dest.parent / "SHERIFFBENCH.md").write_text(
        render_sheriff_scorecard(payload), encoding="utf-8"
    )
    return dest


def _first_target(case: BenchCase) -> Finding | None:
    findings = enrich_findings(heuristic_review(case.diff, case.languages, []))
    return next((item for item in findings if item.rule in case.must_rules), None)


def _precision(case: BenchCase, findings: list[Finding]) -> float | None:
    counted = [item for item in findings if item.rule != "languages"]
    if not counted:
        return 1.0 if case.kind == "hard_negative" else 0.0
    if case.kind == "hard_negative":
        return 1.0 if not counted else 0.0
    expected = set(case.must_rules)
    good = sum(1 for item in counted if item.rule in expected)
    return round(good / len(counted), 4)


def _contract_gaps(findings: list[Finding]) -> list[str]:
    gaps: list[str] = []
    for item in findings:
        if item.rule in {None, "languages"}:
            continue
        payload = finding_payload(item)
        for key in ("message", "reason", "suggestion", "verify"):
            if not payload.get(key):
                gaps.append(f"{item.rule}:{key}")
    return gaps


def _deterministic(case: BenchCase, findings: list[Finding]) -> bool:
    again = heuristic_review(case.diff, case.languages, [])
    left = sorted(
        fingerprint(item, bucket=1) for item in findings if item.rule != "languages"
    )
    right = sorted(
        fingerprint(item, bucket=1) for item in again if item.rule != "languages"
    )
    return left == right


def _closed_loop_rate(tmp: Path) -> dict[str, Any]:
    from quality_gates.review.bench import run_heuristic_suite

    scorecard = run_heuristic_suite(tmp=tmp, closed_loop=True)
    resolved = [
        item
        for item in scorecard.get("results") or []
        if (item.get("closed_loop") or {}).get("resolved")
    ]
    attempted = [
        item
        for item in scorecard.get("results") or []
        if (item.get("closed_loop") or {}).get("status")
        not in {"skipped", "no-path", None}
    ]
    return {
        "attempted": len(attempted),
        "resolved": len(resolved),
        "resolution_rate": (
            round(len(resolved) / len(attempted), 4) if attempted else None
        ),
    }


def calculate_rsvi(
    *,
    r_crit: float,
    false_positive_rate: float,
    r_multi: float,
    a_fix: float,
    b_false: float,
) -> dict[str, float]:
    """Calculate the Review Signal & Velocity Index (RSVI).

    RSVI balances deep defect detection against developer velocity:
    RSVI = 100 * (0.35 * R_crit + 0.20 * (1 - FP) + 0.15 * R_multi + 0.15 * A_fix + 0.15 * (1 - B_false))
    """
    score = 100.0 * (
        0.35 * max(0.0, min(1.0, r_crit))
        + 0.20 * (1.0 - max(0.0, min(1.0, false_positive_rate)))
        + 0.15 * max(0.0, min(1.0, r_multi))
        + 0.15 * max(0.0, min(1.0, a_fix))
        + 0.15 * (1.0 - max(0.0, min(1.0, b_false)))
    )
    return {
        "rsvi": round(score, 2),
        "r_crit": round(r_crit, 4),
        "false_positive_rate": round(false_positive_rate, 4),
        "r_multi": round(r_multi, 4),
        "a_fix": round(a_fix, 4),
        "b_false": round(b_false, 4),
    }
