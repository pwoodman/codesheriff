"""Dependency-aware, explainable quality execution planning."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from quality_gates import GATES
from quality_gates.change_manifest import ChangeManifest
from quality_gates.config import QualityConfig
from quality_gates.risk import triggered_capabilities


@dataclass(frozen=True)
class PlannedTask:
    name: str
    required: bool
    prerequisites: tuple[str, ...]
    inputs: tuple[str, ...]
    reason: str
    permission: str
    status: str = "selected"
    exclusion_reason: str | None = None
    reused_evidence: str | None = None
    uncertainty: str | None = None
    fallback_scope: str | None = None
    execution_count: int = 1
    estimated_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_PREREQUISITES = {
    "compile": ("security",),
    "ui": ("compile",),
    "coverage": ("test",),
    "migration": ("contract",),
}


def order_by_prerequisites(gates: list[str]) -> list[str]:
    selected = set(gates)
    ordered: list[str] = []
    visited: set[str] = set()

    def visit(gate: str) -> None:
        if gate in visited:
            return
        visited.add(gate)
        for prereq in _PREREQUISITES.get(gate, ()):
            if prereq in selected and prereq not in visited:
                visit(prereq)
        ordered.append(gate)

    for gate in gates:
        visit(gate)
    return ordered


_TRUSTED_ISOLATED_GATES = {
    "coverage",
    "ui",
    "compile",
    "test",
    "migration",
    "authorization",
    "resilience",
    "mutation",
    "performance",
}
_ESTIMATED_MS = {
    "format": 2_000,
    "lint": 8_000,
    "security": 15_000,
    "test": 60_000,
    "compile": 90_000,
    "coverage": 120_000,
    "review": 20_000,
    "ui": 90_000,
}


def _uncertainty_context(manifest: ChangeManifest | None) -> tuple[str, str]:
    uncertainty = (
        "full repository assessment"
        if manifest is None
        else (
            "change discovery failed; fallback scope"
            if manifest.state == "unknown"
            else "deterministic change manifest"
        )
    )
    fallback_scope = "repository-wide" if manifest is None else "scoped"
    return uncertainty, fallback_scope


def _selection_reason(
    manifest: ChangeManifest | None, path_count: int, risk: bool
) -> str:
    if manifest is None:
        return "selected by configured gate policy"
    if risk:
        return f"risk-triggered by {path_count} changed path(s)"
    return f"selected for {path_count} changed path(s)"


def _reused_evidence(root: Path | None, gate: str) -> str | None:
    if root is None:
        return None
    report = root / ".quality-reports" / f"{gate}.json"
    return f"existing {gate} artifact present" if report.is_file() else None


def _build_selected_task(
    gate: str,
    *,
    selected: set[str],
    paths: tuple[str, ...],
    config: QualityConfig,
    manifest: ChangeManifest | None,
    root: Path | None,
    uncertainty: str,
    fallback_scope: str,
) -> PlannedTask:
    prerequisites = tuple(
        item for item in _PREREQUISITES.get(gate, ()) if item in selected
    )
    risk = gate in triggered_capabilities(list(paths))
    permission = (
        "trusted isolated worker" if gate in _TRUSTED_ISOLATED_GATES else "read-only"
    )
    return PlannedTask(
        name=gate,
        required=gate in config.fail_on or risk,
        prerequisites=prerequisites,
        inputs=paths,
        reason=_selection_reason(manifest, len(paths), risk),
        permission=permission,
        status="selected",
        reused_evidence=_reused_evidence(root, gate),
        uncertainty=uncertainty,
        fallback_scope=fallback_scope,
        execution_count=1,
        estimated_ms=_ESTIMATED_MS.get(gate, 5_000),
    )


def _build_excluded_task(gate: str) -> PlannedTask:
    return PlannedTask(
        name=gate,
        required=False,
        prerequisites=(),
        inputs=(),
        reason="excluded from execution plan",
        permission="none",
        status="excluded",
        exclusion_reason="not applicable to changed surface or excluded by configuration",
        execution_count=0,
        estimated_ms=0,
    )


def build_plan(
    gates: list[str],
    config: QualityConfig,
    manifest: ChangeManifest | None,
    all_gates: tuple[str, ...] | list[str] | None = None,
    root: Path | None = None,
    time_budget_seconds: int | None = None,
) -> list[PlannedTask]:
    paths = tuple(manifest.paths) if manifest else ()
    sorted_gates = order_by_prerequisites(gates)
    selected = set(sorted_gates)
    uncertainty, fallback_scope = _uncertainty_context(manifest)

    plan: list[PlannedTask] = [
        _build_selected_task(
            gate,
            selected=selected,
            paths=paths,
            config=config,
            manifest=manifest,
            root=root,
            uncertainty=uncertainty,
            fallback_scope=fallback_scope,
        )
        for gate in sorted_gates
    ]
    if time_budget_seconds is not None:
        spent = 0
        budgeted: list[PlannedTask] = []
        for item in plan:
            if item.required or spent + item.estimated_ms <= time_budget_seconds * 1000:
                spent += item.estimated_ms
                budgeted.append(item)
            else:
                budgeted.append(
                    replace(
                        item,
                        status="deferred",
                        exclusion_reason="deferred by time budget (advisory checks only)",
                        execution_count=0,
                    )
                )
        plan = budgeted

    pool = list(all_gates or GATES)
    plan.extend(_build_excluded_task(gate) for gate in pool if gate not in selected)
    return plan


def render_plan(plan: list[PlannedTask]) -> str:
    lines = ["Quality execution plan:"]
    selected_tasks = [t for t in plan if t.status == "selected"]
    excluded_tasks = [t for t in plan if t.status in {"excluded", "deferred"}]
    for item in selected_tasks:
        needs = f"; needs {', '.join(item.prerequisites)}" if item.prerequisites else ""
        reused = f"; reused: {item.reused_evidence}" if item.reused_evidence else ""
        scope_note = f"; scope: {item.fallback_scope}" if item.fallback_scope else ""
        lines.append(
            f"- {item.name}: {'required' if item.required else 'advisory'}; {item.reason}; estimate {_fmt_estimate(item.estimated_ms)}{needs}; {item.permission}{reused}{scope_note}"
        )
    if excluded_tasks:
        lines.append("\nExcluded gates:")
        for item in excluded_tasks:
            lines.append(f"- {item.name}: {item.status} ({item.exclusion_reason})")
    lines.append(
        f"\nSummary: {len(selected_tasks)} check(s) selected, {len(excluded_tasks)} excluded."
    )
    return "\n".join(lines)


def _fmt_estimate(value: int) -> str:
    return f"{value / 1000:.0f}s" if value >= 1000 else f"{value}ms"


def write_plan(root: Path, plan: list[PlannedTask]) -> Path:
    path = root / ".quality-reports" / "execution-plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"tasks": [item.to_dict() for item in plan]}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
