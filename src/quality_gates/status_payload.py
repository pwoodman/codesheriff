"""Status payload helpers shared by CLI and agent tools."""

from __future__ import annotations

from pathlib import Path

from quality_gates.oracle import remaining_from_reports
from quality_gates.paths import project_root


def status_payload(root: Path | None = None) -> dict:
    """Return the status payload with project health overview."""
    return remaining_from_reports(root or Path("."))


def hooks_payload(root: Path | None = None) -> dict:
    """Return hooks and automation status."""
    root = root or project_root()
    hooks: list[dict] = []
    precommit = root / ".pre-commit-config.yaml"
    hooks_dir = root / ".git" / "hooks"

    if precommit.is_file():
        installed = (hooks_dir / "pre-commit").exists()
        hooks.append(
            {
                "type": "pre-commit",
                "file": str(precommit),
                "installed": installed,
                "status": "active" if installed else "configured",
            }
        )

    if hooks_dir.is_dir():
        for hook_file in ["pre-commit", "pre-push", "commit-msg"]:
            hook_path = hooks_dir / hook_file
            if hook_path.exists():
                hooks.append(
                    {
                        "type": hook_file,
                        "file": str(hook_path),
                        "installed": True,
                        "status": "active",
                    }
                )

    app_dir = root / ".quality-app"
    if app_dir.is_dir():
        hooks.append(
            {
                "type": "webhook",
                "file": str(app_dir),
                "installed": True,
                "status": "active",
            }
        )

    workflow_dir = root / ".github" / "workflows"
    automations: list[dict] = []
    if workflow_dir.is_dir():
        for wf in workflow_dir.glob("*.yml"):
            text = wf.read_text(encoding="utf-8", errors="ignore")
            if "sheriff" in text.lower() or "quality" in text.lower():
                automations.append(
                    {
                        "trigger": "github-action",
                        "file": str(wf),
                        "status": "configured",
                    }
                )

    if app_dir.is_dir():
        automations.append(
            {
                "trigger": "webhook",
                "file": str(app_dir),
                "status": "configured",
            }
        )

    return {"hooks": hooks, "automations": automations}


def agent_payload(
    root: Path | None = None, action: str = "context", finding_id: str | None = None
) -> dict:
    """Return agent context payload."""
    root = root or project_root()
    result: dict = {"action": action, "project_root": str(root)}

    if action in {"context", "findings"}:
        result["status"] = status_payload(root)

    if action == "next":
        payload = status_payload(root)
        result["next"] = (payload.get("playbook") or {}).get("next", {})
        result["green"] = payload.get("green")

    if finding_id:
        from quality_gates.oracle import finding_from_reports

        result["finding"] = finding_from_reports(root, finding_id)

    return result
