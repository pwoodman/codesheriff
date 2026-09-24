"""Implementation of ``codesheriff doctor`` (toolchain inventory + install).

Extracted from ``cli.py`` to keep the command module readable; ``cli.py`` still
owns the argument parser and calls ``doctor()`` as the entry point.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import detect_languages
from quality_gates.installers import (
    ensure_checkstyle,
    ensure_gitleaks,
    ensure_golangci_lint,
    ensure_google_java_format,
    ensure_node_tooling,
    ensure_osv_scanner,
    write_github_path,
)
from quality_gates.paths import cache_dir
from quality_gates.tool_manifest import load_tool_manifest, platform_id
from quality_gates.tools import tool_version, which


def validate_install(config: QualityConfig, *, install: bool) -> int | None:
    """Validate that --install is permitted and perform installation if requested.

    Returns a non-zero exit code if validation fails, otherwise ``None``.
    """
    if install and config.offline:
        print(
            "doctor --install is unavailable while quality.offline=true",
            file=sys.stderr,
        )
        return 2
    if install:
        _install_all()
        write_github_path()
    return None


def select_tools(
    root: Path, config: QualityConfig, detected: dict[str, object]
) -> list:
    manifest = load_tool_manifest()
    language_set = set(detected["languages"])
    kind_set = set(detected["file_kinds"])
    required = set(config.required_tools)
    return [
        tool
        for tool in manifest.tools
        if language_set.intersection(tool.languages)
        or kind_set.intersection(tool.file_kinds)
        or required.intersection({tool.id})
        or set(tool.capabilities).intersection({"security", "dry"})
    ]


def tool_row(
    tool, root: Path, config: QualityConfig, required: set[str]
) -> dict[str, object]:
    path = next(
        (
            found
            for command in tool.commands
            if (
                found := which(
                    command,
                    project=root,
                    prefer_project=config.prefer_project_tools,
                )
            )
        ),
        None,
    )
    if path is None and tool.cache_path:
        cached = cache_dir() / tool.cache_path
        path = str(cached) if cached.is_file() else None
    command = tool.commands[0] if tool.commands else tool.id
    version = (
        tool_version(command, tool.version_args)
        if path and tool.commands
        else tool.version
        if path
        else None
    )
    return {
        "tool": tool.id,
        "path": path,
        "version": version,
        "ok": bool(path),
        "required": tool.id in required,
        "capabilities": list(tool.capabilities),
        "platform_supported": tool.supports_current_platform(),
        "auto_install_supported": tool.install_supported,
        "auto_install_reason": tool.install_reason,
    }


def missing_rows(selected, required: set[str]) -> list[dict[str, object]]:
    known = {tool.id for tool in selected}
    return [
        {
            "tool": tool_id,
            "path": None,
            "version": None,
            "ok": False,
            "required": True,
            "capabilities": [],
            "platform_supported": False,
            "auto_install_supported": False,
            "auto_install_reason": "not present in the tool manifest",
        }
        for tool_id in sorted(required - known)
    ]


def compute_rows(
    root: Path, config: QualityConfig, detected: dict[str, object]
) -> list[dict[str, object]]:
    required = set(config.required_tools)
    selected = select_tools(root, config, detected)
    rows = [tool_row(tool, root, config, required) for tool in selected]
    rows.extend(missing_rows(selected, required))
    return rows


def build_payload(
    root: Path,
    config: QualityConfig,
    detected: dict[str, object],
    rows: list[dict[str, object]],
) -> dict[str, object]:
    missing_required = [
        str(row["tool"]) for row in rows if row["required"] and not row["ok"]
    ]
    missing_optional = [
        str(row["tool"]) for row in rows if not row["required"] and not row["ok"]
    ]
    hooks = _doctor_hooks(root)
    agents = _doctor_agents(root)
    automations = _doctor_automations(root)
    return {
        "platform": platform_id(),
        "cache": str(cache_dir()),
        "trust": config.trust,
        "offline": config.offline,
        "detected": detected,
        "tools": rows,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "hooks": hooks,
        "agents": agents,
        "automations": automations,
    }


def render_console(
    root: Path, config: QualityConfig, payload: dict[str, object]
) -> None:
    rows = payload["tools"]
    print(f"project: {root}")
    print(
        f"platform: {payload['platform']} · trust: {config.trust} · "
        f"offline: {str(config.offline).lower()}"
    )
    print(f"cache: {payload['cache']}")
    width = max(len(row["tool"]) for row in rows)
    for row in rows:
        mark = "ok" if row["ok"] else "missing"
        requirement = "required" if row["required"] else "optional"
        extra = row["version"] or row["path"] or "not on PATH"
        print(f"  {row['tool']:<{width}}  {mark:<8}  {requirement:<8}  {extra}")
    print(
        "\nTip: codesheriff doctor --install (alias --fix) downloads gitleaks,"
        " osv-scanner, golangci-lint, and JS tooling.\n"
        "Other toolchains: use your platform package manager or project bundle.\n"
        "Missing tools report skip, never pass. Untrusted clones: use\n"
        "QUALITY_TRUST=untrusted and skip test/compile/coverage/ui (see docs/BETA_TESTING.md)."
    )
    hooks = payload.get("hooks") or {}
    if hooks.get("precommit") or hooks.get("git_hooks"):
        print("\nHooks:")
        for hk, hv in hooks.items():
            if isinstance(hv, dict):
                status = hv.get("status", "unknown")
                print(f"  {hk}: {status}")
            elif isinstance(hv, list):
                for h in hv:
                    print(f"  {h.get('type', h)}: {h.get('status', 'unknown')}")
    agents = payload.get("agents") or []
    if agents:
        print("\nAgent integrations:")
        for a in agents:
            print(f"  {a}")
    automations = payload.get("automations") or []
    if automations:
        print("\nAutomations:")
        for a in automations:
            print(f"  {a.get('trigger', 'unknown')}: {a.get('status', 'unknown')}")


def doctor(root: Path, config: QualityConfig, *, install: bool, as_json: bool) -> int:
    validation_error = validate_install(config, install=install)
    if validation_error is not None:
        return validation_error
    detected = detect_languages(root, config)
    rows = compute_rows(root, config, detected)
    payload = build_payload(root, config, detected, rows)
    if as_json:
        print(json.dumps(payload, indent=2))
    else:
        render_console(root, config, payload)
    return 1 if payload["missing_required"] else 0


def _install_all() -> None:
    ensure_node_tooling()
    for loader in (
        ensure_gitleaks,
        ensure_osv_scanner,
        ensure_golangci_lint,
        ensure_google_java_format,
        ensure_checkstyle,
    ):
        try:
            loader()
        except (OSError, RuntimeError) as exc:
            print(f"warning: {loader.__name__} failed: {exc}", file=sys.stderr)


def _doctor_hooks(root: Path) -> dict:
    hooks: dict = {}
    precommit = root / ".pre-commit-config.yaml"
    hooks_dir = root / ".git" / "hooks"

    if precommit.is_file():
        hooks["precommit"] = {
            "file": str(precommit),
            "status": "configured",
        }
        if (hooks_dir / "pre-commit").exists():
            hooks["precommit"]["status"] = "active"

    if hooks_dir.is_dir():
        git_hooks = []
        for hook_file in ["pre-commit", "pre-push", "commit-msg"]:
            hook_path = hooks_dir / hook_file
            if hook_path.exists():
                git_hooks.append({"type": hook_file, "status": "active"})
        if git_hooks:
            hooks["git_hooks"] = git_hooks

    return hooks


def _doctor_agents(root: Path) -> list[str]:
    agents: list[str] = []
    for p in [
        root / "AGENTS.md",
        root / ".cursor" / "rules" / "the-code-sheriff.mdc",
        root / ".claude" / "skills" / "the-code-sheriff" / "SKILL.md",
        root / ".github" / "copilot-instructions.md",
    ]:
        if p.exists():
            agents.append(str(p.relative_to(root)))
    return agents


def _doctor_automations(root: Path) -> list[dict]:
    automations: list[dict] = []
    workflow_dir = root / ".github" / "workflows"
    if workflow_dir.is_dir():
        for wf in workflow_dir.glob("*.yml"):
            text = wf.read_text(encoding="utf-8", errors="ignore")
            if "sheriff" in text.lower() or "quality" in text.lower():
                automations.append(
                    {
                        "trigger": "github-action",
                        "file": wf.name,
                        "status": "configured",
                    }
                )
    return automations
