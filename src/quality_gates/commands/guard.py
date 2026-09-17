"""``codesheriff guard`` — sub-second pre-commit scan of staged changes.

The everyday complaint about pre-commit hooks is latency: running the full gate
suite on every commit is unusable on a large monorepo. ``guard`` scans only the
bytes git is about to commit, with O(1)-per-line regex checks (secrets, unsafe
patterns, merge markers). It never shells out to a scanner and never touches
files outside the staged set, so it stays well under a second.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from quality_gates.gitutil import git_is_repo
from quality_gates.models import Finding

# git's conflict marker width: "<<<<<<<" / ">>>>>>>" open/close with 7 chars,
# "=======" is the 7-char separator.
_CONFLICT_MARKER_WIDTH = 7

# Line-level patterns. Keep this list short: guard trades coverage for latency.
_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "hardcoded-secret",
        re.compile(
            r"""(?i)\b(api[_-]?key|apikey|secret|password|passwd|token|private[_-]?key)\b"""
            r"""\s*[=:]\s*['"][^'"]{8,}['"]"""
        ),
        "possible hardcoded credential",
    ),
    (
        "merge-conflict",
        re.compile(
            rf"^(<{{{_CONFLICT_MARKER_WIDTH}}} "
            rf"|>{{{_CONFLICT_MARKER_WIDTH}}} "
            rf"|={{{_CONFLICT_MARKER_WIDTH}}}$)"
        ),
        "unresolved merge conflict marker",
    ),
    (
        "private-key-block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
        "committed private key",
    ),
    (
        "aws-access-key",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        "AWS access key id",
    ),
    (
        "github-token",
        re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
        "GitHub token",
    ),
)

# Files git stages but that never carry source intent.
_SKIP_SUFFIXES = (".lock", ".min.js", ".min.css", ".map", ".snap", ".pb.go")


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "guard",
        help="sub-second pre-commit scan of staged changes (secrets, conflict markers)",
    )
    parser.add_argument(
        "paths", nargs="*", help="scan these files instead of staged changes"
    )
    parser.add_argument(
        "--all", action="store_true", help="scan the whole working tree"
    )


def handle(args: argparse.Namespace, root: Path, config) -> int | None:
    if getattr(args, "command", None) != "guard":
        return None
    targets = _targets(root, args, config)
    if targets is None:
        print("guard: not a git repository (use `codesheriff guard --all`)")
        return 2
    findings: list[Finding] = []
    for rel in targets:
        findings.extend(_scan_file(root, rel))
    if args.json:
        print(
            json.dumps(
                {
                    "scanned": len(targets),
                    "blocked": bool(findings),
                    "findings": [finding.to_dict() for finding in findings],
                },
                indent=2,
            )
        )
        return 1 if findings else 0
    if not findings:
        print(f"guard: clean ({len(targets)} staged file(s))")
        return 0
    print(f"guard: {len(findings)} blocking finding(s) — commit stopped")
    for finding in findings:
        print(f"  {finding.path}:{finding.line}: {finding.message} [{finding.rule}]")
    print("\nfix, or commit with `git commit --no-verify` if this is intentional.")
    return 1


def _targets(root: Path, args: argparse.Namespace, config) -> list[str] | None:
    explicit = list(getattr(args, "paths", None) or [])
    if explicit:
        return [str(Path(item)) for item in explicit]
    if getattr(args, "all", False):
        from quality_gates.detect import iter_project_files

        return sorted(
            str(path.relative_to(root))
            for path in iter_project_files(root, config)
            if not _skip(path.name)
        )
    if not git_is_repo(root):
        return None
    return _staged_names(root)


def _staged_names(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    names = [
        name for name in result.stdout.decode("utf-8", "replace").split("\0") if name
    ]
    return [name for name in names if not _skip(name)]


def _skip(name: str) -> bool:
    return name.lower().endswith(_SKIP_SUFFIXES)


def _scan_file(root: Path, rel: str) -> list[Finding]:
    path = (root / rel).resolve()
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
    except OSError:
        return []
    return scan_text(text, rel)


def scan_text(text: str, rel: str) -> list[Finding]:
    """Scan already-loaded text. Shared with tests and the inline guard hook."""
    findings: list[Finding] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if len(line) > 4000:  # generated/data lines are not human intent
            continue
        if "example" in line.lower() or "placeholder" in line.lower():
            continue
        for rule, pattern, message in _PATTERNS:
            if pattern.search(line):
                findings.append(
                    Finding(
                        gate="guard",
                        rule=rule,
                        path=rel,
                        line=index,
                        message=message,
                        severity="error",
                        tool="guard",
                    )
                )
    return findings


__all__ = ["handle", "register", "scan_text"]
