"""Safe, local MVP utilities exposed by the product-evaluation commands."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from quality_gates.detect import (
    detect_languages,
    discover_workspaces,
    filter_workspaces_for_changes,
)
from quality_gates.redact import redact_secrets
from quality_gates.review.context_extra import owners_for, parse_codeowners

_SECRET_KEY = re.compile(r"(?i)(token|password|secret|api[_-]?key|private[_-]?key)")


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_policy_bundle(path: Path, key: str) -> dict[str, Any]:
    bundle = _json(path)
    signature = str(bundle.pop("signature", ""))
    canonical = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
    actual = hmac.new(key.encode(), canonical, hashlib.sha256).hexdigest()
    return {
        "bundle": str(path),
        "version": bundle.get("version"),
        "algorithm": "hmac-sha256",
        "valid": bool(signature) and hmac.compare_digest(signature, actual),
        "policy": bundle.get("policy", {}),
    }


def export_trace(root: Path) -> dict[str, Any]:
    report = root / ".quality-reports" / "quality-report.json"
    payload = _json(report) if report.is_file() else {"results": []}
    events = []
    for result in payload.get("results", []):
        evidence = result.get("evidence") or {}
        events.append(
            {
                "gate": result.get("name"),
                "command": result.get("command", []),
                "input_scope": evidence.get("changed_paths", []),
                "evidence": evidence,
                "trust_decision": result.get("safety") or "local",
                "status": result.get("status"),
            }
        )
    return {"schema_version": "1.0.0", "static_replay_only": True, "events": events}


def redaction_preview(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    redacted = redact_secrets(raw)
    try:
        value = json.loads(redacted)
    except json.JSONDecodeError:
        value = redacted

    def scrub(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: "<redacted>" if _SECRET_KEY.search(key) else scrub(value)
                for key, value in item.items()
            }
        if isinstance(item, list):
            return [scrub(value) for value in item]
        return item

    preview = scrub(value)
    serialized = (
        json.dumps(preview, indent=2) if not isinstance(preview, str) else preview
    )
    return {
        "source": str(path),
        "redactions": serialized.count("<redacted>"),
        "preview": preview,
    }


def cache_provenance(cache: Path, *, offline: bool) -> dict[str, Any]:
    entries = list(cache.glob("*/*.json")) if cache.is_dir() else []
    ages = [max(0, int(time.time() - item.stat().st_mtime)) for item in entries]
    return {
        "path": str(cache),
        "entries": len(entries),
        "offline": offline,
        "provenance": "local deterministic result cache",
        "oldest_age_seconds": max(ages, default=0),
        "newest_age_seconds": min(ages, default=0),
        "stale": bool(ages and max(ages) > 7 * 24 * 3600),
    }


def risk_zones(paths: Iterable[str]) -> dict[str, list[str]]:
    zones = {
        "authentication": ("auth", "login", "session", "identity"),
        "authorization": ("authoriz", "permission", "rbac", "acl", "privileg"),
        "payment": ("payment", "billing", "checkout", "stripe", "pci"),
    }
    result = {name: [] for name in zones}
    for path in paths:
        lowered = path.lower()
        for name, markers in zones.items():
            if any(marker in lowered for marker in markers):
                result[name].append(path)
    return {name: values for name, values in result.items() if values}


def enrich_findings_owners(
    root: Path, findings: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    rules = parse_codeowners(root)
    enriched = []
    for finding in findings:
        row = dict(finding)
        if row.get("path"):
            row["owner"] = owners_for([str(row["path"])], rules)
        row["fingerprint"] = fingerprint_from_row(row)
        enriched.append(row)
    return enriched


def fingerprint_from_row(row: dict[str, Any]) -> str:
    return hashlib.sha256(
        "|".join(
            str(row.get(key, "")) for key in ("gate", "rule", "path", "line", "message")
        ).encode()
    ).hexdigest()[:24]


def sarif_baseline(root: Path, source: Path | None = None) -> dict[str, Any]:
    if source:
        payload = _json(source)
        findings = []
        for run in payload.get("runs", []):
            for item in run.get("results", []):
                props = item.get("properties") or {}
                locations = item.get("locations") or [{}]
                physical = locations[0].get("physicalLocation") or {}
                region = physical.get("region") or {}
                findings.append(
                    {
                        "gate": "sarif",
                        "rule": item.get("ruleId"),
                        "message": (item.get("message") or {}).get("text", ""),
                        "path": (physical.get("artifactLocation") or {}).get("uri"),
                        "line": region.get("startLine"),
                        "owner": props.get("owner", []),
                        "suppression": props.get("suppression"),
                    }
                )
    else:
        artifact = root / ".quality-reports" / "findings-last.json"
        findings = _json(artifact).get("findings", []) if artifact.is_file() else []
    return {
        "schema_version": "1.0.0",
        "findings": enrich_findings_owners(root, findings),
    }


def fleet_metrics(root: Path) -> dict[str, Any]:
    report = root / ".quality-reports" / "quality-report.json"
    payload = _json(report) if report.is_file() else {"results": []}
    rows = []
    for result in payload.get("results", []):
        for finding in result.get("findings", []):
            rows.append(
                {
                    "rule": finding.get("rule") or result.get("name"),
                    "language": finding.get("language"),
                    "severity": finding.get("severity"),
                }
            )
    return {
        "schema_version": "1.0.0",
        "privacy": "opt-in; no paths, source, users, or finding messages",
        "metrics": rows,
    }


def static_benchmark(roots: Iterable[Path], config: Any) -> dict[str, Any]:
    """Inventory supplied checkouts only; this never runs repository code or tools."""
    scanned = []
    for root in roots:
        scanned.append(
            {
                "root": str(root),
                "detect": detect_languages(root, config),
                "trust": "untrusted-static-only",
            }
        )
    return {"schema_version": "1.0.0", "execution": "none", "repositories": scanned}


def select_monorepo_targets(root: Path, changed_paths: list[str]) -> dict[str, Any]:
    """Select existing workspace boundaries; adapters are intentionally not executed."""
    workspaces = filter_workspaces_for_changes(discover_workspaces(root), changed_paths)
    return {
        "changed_paths": changed_paths,
        "targets": [
            {"path": workspace.path, "manifest": workspace.manifest}
            for workspace in workspaces
        ],
        "execution": "selection-only",
    }
