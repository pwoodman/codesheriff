"""``codesheriff migrate`` — move a repo onto the current branding.

Renames ``quality.toml`` to ``sheriff.toml``, relocates the committed data
directory ``.quality/`` to ``.sheriff/``, and rewrites legacy
``quality:ignore`` markers so nothing silently stops working.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".sh",
    ".sql",
    ".yml",
    ".yaml",
    ".toml",
    ".md",
}
_MARKER = re.compile(r"(?<![A-Za-z0-9_-])quality:(ignore)", re.I)
_SECTION = re.compile(r"^\[quality\]", re.M)
_SUBSECTION = re.compile(r"^\[quality\.", re.M)


def _rewrite_config_key(path: Path, *, dry_run: bool) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not _SECTION.search(text) and not _SUBSECTION.search(text):
        return None
    updated = _SUBSECTION.sub("[sheriff.", text)
    updated = _SECTION.sub("[sheriff]", updated)
    if not dry_run:
        path.write_text(updated, encoding="utf-8")
    return f"rewrite [quality] -> [sheriff] in {path.name}"


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "migrate",
        help="rename quality.toml/.quality and legacy markers to the sheriff brand",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show the plan without changing files"
    )
    parser.add_argument("--json", action="store_true")


def handle(args: argparse.Namespace, root: Path, config) -> int | None:
    if getattr(args, "command", None) != "migrate":
        return None
    actions: list[str] = []

    legacy_cfg = root / "quality.toml"
    new_cfg = root / "sheriff.toml"
    if legacy_cfg.is_file() and not new_cfg.exists():
        actions.append("rename quality.toml -> sheriff.toml")
        if not args.dry_run:
            legacy_cfg.rename(new_cfg)
    if new_cfg.is_file():
        rewrite = _rewrite_config_key(new_cfg, dry_run=args.dry_run)
        if rewrite:
            actions.append(rewrite)

    legacy_dir = root / ".quality"
    new_dir = root / ".sheriff"
    if legacy_dir.is_dir() and not new_dir.exists():
        actions.append("move .quality/ -> .sheriff/")
        if not args.dry_run:
            shutil.move(str(legacy_dir), str(new_dir))

    rewrites = _rewrite_markers(root, dry_run=args.dry_run)
    actions.extend(rewrites)

    if args.json:
        import json

        print(json.dumps({"dry_run": args.dry_run, "actions": actions}, indent=2))
    elif not actions:
        print("already on the sheriff brand; nothing to do")
    else:
        verb = "would" if args.dry_run else "did"
        print(f"{verb} apply {len(actions)} change(s):")
        for item in actions:
            print(f"  {item}")
    return 0


def _rewrite_markers(root: Path, *, dry_run: bool) -> list[str]:
    changes: list[str] = []
    for path in _iter_sources(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not _MARKER.search(text):
            continue
        updated = _MARKER.sub(r"codesheriff:\1", text)
        rel = path.relative_to(root).as_posix()
        changes.append(f"rewrite quality:ignore -> codesheriff:ignore in {rel}")
        if not dry_run:
            path.write_text(updated, encoding="utf-8")
    return changes


def _iter_sources(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(
            part in {".git", ".venv", "node_modules", "__pycache__"}
            for part in path.parts
        ):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            yield path


__all__ = ["handle", "register"]
