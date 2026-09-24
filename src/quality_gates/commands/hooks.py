"""codesheriff hooks — manage git hooks, pre-commit, and automations."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def register(sub: object) -> None:

    parser = sub.add_parser(
        "hooks",
        help="manage git hooks, pre-commit config, and automation triggers",
    )
    parser.add_argument(
        "action",
        choices=["list", "install", "uninstall", "status", "add", "remove"],
        default="status",
        nargs="?",
        help="action to perform",
    )
    parser.add_argument(
        "--hook-type",
        choices=["pre-commit", "pre-push", "commit-msg"],
        help="hook type",
    )
    parser.add_argument("--name", help="hook name (for add/remove)")
    parser.add_argument("--hook-command", help="hook command (for add)")
    parser.add_argument(
        "--trigger",
        choices=["pre-commit", "pre-push", "pr", "push", "schedule"],
        help="automation trigger",
    )
    parser.add_argument("--event", help="event to match (e.g., pull_request, push)")
    parser.add_argument("--url", help="webhook URL for automation")
    parser.add_argument(
        "--list-all", action="store_true", help="list all configured hooks"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")


def handle(args: object, root: Path, config) -> int | None:
    if getattr(args, "command", None) != "hooks":
        return None

    action = getattr(args, "action", "status") or "status"
    as_json = getattr(args, "json", False)

    if action == "status":
        return _status(root, as_json)
    if action == "list":
        return _list_hooks(root, as_json, getattr(args, "list_all", False))
    if action == "install":
        return _install_hooks(root)
    if action == "uninstall":
        return _uninstall_hooks(root)
    if action == "add":
        return _add_hook(root, args)
    if action == "remove":
        return _remove_hook(root, args)

    return None


def _status(root: Path, as_json: bool) -> int:
    from quality_gates.status_payload import hooks_payload

    hooks = hooks_payload(root)["hooks"]

    if as_json:
        print(json.dumps({"hooks": hooks, "root": str(root)}, indent=2))
    else:
        if not hooks:
            print("No hooks configured. Run: codesheriff setup --hooks")
        else:
            print("Configured hooks:")
            for h in hooks:
                print(f"  {h['type']}: {h['status']} ({h['file']})")
        print()
        print("Run codesheriff hooks install to activate git hooks.")

    return 0


def _list_hooks(root: Path, as_json: bool, all_hooks: bool) -> int:
    precommit = root / ".pre-commit-config.yaml"
    hooks_dir = root / ".git" / "hooks"

    result: dict = {"git_hooks": [], "automations": []}

    if precommit.is_file():
        text = precommit.read_text(encoding="utf-8")
        result["git_hooks"].append(
            {
                "type": "pre-commit",
                "config": str(precommit),
                "content": text if all_hooks else "[redacted]",
            }
        )

    if hooks_dir.is_dir():
        for hook_file in sorted(hooks_dir.iterdir()):
            if hook_file.is_file() and hook_file.name != "sample":
                result["git_hooks"].append(
                    {
                        "type": hook_file.name,
                        "path": str(hook_file),
                    }
                )

    result["automations"].extend(_list_automations(root))

    if as_json:
        print(json.dumps(result, indent=2))
    else:
        print("Git hooks:")
        for h in result["git_hooks"]:
            print(f"  {h['type']}")
        print("Automations:")
        for a in result["automations"]:
            print(f"  {a.get('trigger')}: {a.get('status')}")

    return 0


def _install_hooks(root: Path) -> int:
    if not (root / ".pre-commit-config.yaml").is_file():
        print("No .pre-commit-config.yaml found. Run: codesheriff setup --hooks")
        return 1

    try:
        result = subprocess.run(
            [
                "pre-commit",
                "install",
                "--hook-type",
                "pre-commit",
                "--hook-type",
                "pre-push",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            print("Git hooks installed. pre-commit and pre-push are active.")
            return 0
        print(f"Hook install failed: {result.stderr}")
        return 1
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"Hook install error: {exc}")
        return 1


def _uninstall_hooks(root: Path) -> int:
    hooks_dir = root / ".git" / "hooks"
    if not hooks_dir.is_dir():
        print("No git hooks directory found.")
        return 1

    removed = []
    for hook_file in ["pre-commit", "pre-push", "commit-msg"]:
        hook_path = hooks_dir / hook_file
        if hook_path.exists() and hook_path.is_file():
            hook_path.unlink()
            removed.append(hook_file)

    if removed:
        print(f"Removed hooks: {', '.join(removed)}")
    else:
        print("No Sheriff hooks found to remove.")
    return 0


def _add_hook(root: Path, args: object) -> int:
    hook_type = args.hook_type or "pre-commit"
    name = getattr(args, "name", "custom")
    command = getattr(args, "hook_command", "")

    if not command:
        print("--hook-command is required for adding a hook.")
        return 1

    precommit = root / ".pre-commit-config.yaml"
    if not precommit.is_file():
        print("No .pre-commit-config.yaml found. Run: codesheriff setup --hooks first.")
        return 1

    print(f"Hook '{name}' ({hook_type}) would run: {command}")
    print("Note: Edit .pre-commit-config.yaml manually for advanced hooks.")
    return 0


def _remove_hook(root: Path, args: object) -> int:
    name = getattr(args, "name", "")
    if not name:
        print("--name is required for removing a hook.")
        return 1

    hooks_dir = root / ".git" / "hooks"
    hook_path = hooks_dir / name
    if hook_path.exists():
        hook_path.unlink()
        print(f"Removed hook: {name}")
        return 0

    precommit = root / ".pre-commit-config.yaml"
    if precommit.is_file():
        print(f"Note: {name} may be configured in .pre-commit-config.yaml")

    print(f"Hook '{name}' not found.")
    return 1


def _is_precommit_installed(root: Path) -> bool:
    hooks_dir = root / ".git" / "hooks"
    return (hooks_dir / "pre-commit").exists()


def _list_automations(root: Path) -> list[dict]:
    from quality_gates.status_payload import hooks_payload

    return hooks_payload(root)["automations"]
