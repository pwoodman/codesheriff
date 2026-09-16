"""Inline and file-based overrides for findings.

Teams need a cheap way to say "this hit is known" without a SaaS dashboard.
Inline comments win for a single line; the ignore file is the durable,
commit-together record; signed expiring merge-policy exceptions live in
``quality.exceptions``.  Rules may carry a stable per-finding ``fingerprint``
so accepting one hit does not silently waive every future hit of that rule.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from quality_gates.models import Finding, GateResult
from quality_gates.review.parse import fingerprint
from quality_gates.review.routing import glob_match

IGNORE_FILE = ".sheriff/ignore.toml"
LEGACY_IGNORE_FILES = (".quality/ignore.toml", ".quality-gates-ignore.toml")
IGNORE_RE = re.compile(
    r"(?:quality|codesheriff):\s*ignore(?:-(next-line|file))?(?:\s+([^\s#]+))?",
    re.I,
)


def ignore_path(root: Path) -> Path:
    """Committed suppression file, preferring ``.sheriff`` over legacy names."""
    for name in (IGNORE_FILE, *LEGACY_IGNORE_FILES):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return root / IGNORE_FILE


@dataclass(frozen=True)
class IgnoreRule:
    rule: str | None = None
    gate: str | None = None
    path: str | None = None
    reason: str = ""
    owner: str = ""
    expires: str | None = None
    fingerprint: str | None = None
    anchor: str | None = None

    def active(self) -> bool:
        if not self.expires:
            return True
        try:
            expires = datetime.fromisoformat(self.expires.replace("Z", "+00:00"))
        except ValueError:
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return expires > datetime.now(UTC)


def load_ignore_rules(root: Path, *, include_expired: bool = False) -> list[IgnoreRule]:
    out: list[IgnoreRule] = []
    for path in _ignore_files(root):
        out.extend(_load_ignore_file(path, include_expired=include_expired))
    return out


def _ignore_files(root: Path) -> list[Path]:
    seen: list[Path] = []
    for name in (IGNORE_FILE, *LEGACY_IGNORE_FILES):
        candidate = root / name
        if candidate.is_file() and candidate not in seen:
            seen.append(candidate)
    return seen


def _load_ignore_file(path: Path, *, include_expired: bool) -> list[IgnoreRule]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    rows = data.get("ignore") or data.get("ignores") or []
    if not isinstance(rows, list):
        return []
    out: list[IgnoreRule] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        rule = IgnoreRule(
            rule=_opt_str(item.get("rule")),
            gate=_opt_str(item.get("gate")),
            path=_opt_str(item.get("path")),
            reason=str(item.get("reason") or "").strip(),
            owner=str(item.get("owner") or "").strip(),
            expires=_opt_str(item.get("expires")),
            fingerprint=_opt_str(item.get("fingerprint")),
            anchor=_opt_str(item.get("anchor")),
        )
        if rule.active() or include_expired:
            out.append(rule)
    return out


def fingerprint_parts(finding_id: str) -> tuple[str, str, str]:
    """Split ``path|rule|line`` back into its pieces (best-effort)."""
    path, _, rest = finding_id.partition("|")
    rule, _, line = rest.partition("|")
    return path, rule.lower(), line


def anchor_for(finding: Finding, root: Path | None = None) -> str | None:
    """Content hash of the finding's source line, stable across line drift.

    A line-number-only fingerprint re-opens a suppressed finding the moment an
    unrelated edit shifts it down the file. The anchor captures *what the code
    said*, so the waiver follows the code instead of the line number.
    """
    text = finding.snippet
    if not text and root is not None and finding.path and finding.line:
        try:
            lines = (
                (root / finding.path)
                .read_text(encoding="utf-8", errors="replace")
                .splitlines()
            )
        except OSError:
            lines = []
        if 1 <= finding.line <= len(lines):
            text = lines[finding.line - 1]
    payload = (text or finding.message or "").strip()
    if not payload:
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def apply_ignores(
    results: list[GateResult], root: Path, extra: list[IgnoreRule] | None = None
) -> list[GateResult]:
    rules = load_ignore_rules(root) + list(extra or [])
    for result in results:
        kept: list[Finding] = []
        ignored = 0
        recorded: list[dict[str, Any]] = []
        for item in result.findings:
            why = ignore_reason(root, item, rules)
            if why:
                ignored += 1
                recorded.append(
                    {
                        "gate": item.gate,
                        "rule": item.rule,
                        "path": item.path,
                        "line": item.line,
                        "message": item.message,
                        "reason": why,
                    }
                )
                item.severity = "info"
                item.reason = why
                continue
            kept.append(item)
        if ignored:
            result.findings = kept
            result.notes.append(f"ignored {ignored} finding(s) via suppression rules")
            if result.status == "fail" and not result.error_count():
                result.status = "pass"
        if recorded:
            result.evidence["suppressed"] = recorded
    return results


def ignore_reason(
    root: Path, finding: Finding, rules: list[IgnoreRule] | None = None
) -> str | None:
    """Return the ignore reason, or None if the finding still counts."""
    posix = (finding.path or "").replace("\\", "/").lstrip("./")
    rule_id = (finding.rule or "").strip()
    anchor = None
    for item in rules or []:
        if not item.active():
            continue
        if item.fingerprint or item.anchor:
            mode = _identity_mode(item, finding, rule_id, root, anchor)
            if mode:
                owner = f" ({item.owner})" if item.owner else ""
                suffix = " (matched after line drift)" if mode == "anchor" else ""
                return f"ignored{owner}: {item.reason or 'accepted finding'}{suffix}"
            continue
        if item.gate and item.gate != finding.gate:
            continue
        if item.rule and item.rule not in {rule_id, "*", f"{finding.gate}:{rule_id}"}:
            continue
        if item.path and posix and not _path_match(posix, item.path):
            continue
        if item.path and not posix and not item.path.startswith("*"):
            continue
        owner = f" ({item.owner})" if item.owner else ""
        return f"ignored{owner}: {item.reason or 'suppression file'}"
    if posix and finding.line:
        inline = _inline_reason(root / posix, finding.line, rule_id, finding.gate)
        if inline:
            return inline
    if posix:
        file_reason = _file_header_ignore(root / posix, rule_id, finding.gate)
        if file_reason:
            return file_reason
    return None


def _identity_match(
    item: IgnoreRule,
    finding: Finding,
    rule_id: str,
    root: Path,
    anchor: str | None,
) -> bool:
    """Match an exact fingerprint, or a drifted finding via its content anchor."""
    return _identity_mode(item, finding, rule_id, root, anchor) is not None


def _identity_mode(
    item: IgnoreRule,
    finding: Finding,
    rule_id: str,
    root: Path,
    anchor: str | None,
) -> str | None:
    """How a waiver matched: ``exact``, ``anchor`` (post-drift), or ``None``."""
    if item.fingerprint and item.fingerprint == fingerprint(finding, bucket=1):
        return "exact"
    if not item.anchor:
        return None
    if item.rule and item.rule not in {rule_id, "*", f"{finding.gate}:{rule_id}"}:
        return None
    if item.path and not _path_match((finding.path or "").lstrip("./"), item.path):
        return None
    current = anchor if anchor is not None else anchor_for(finding, root)
    return "anchor" if current and current == item.anchor else None


def append_ignore(
    root: Path,
    *,
    rule: str,
    path: str | None = None,
    gate: str | None = None,
    reason: str,
    owner: str,
    days: int | None = 90,
    fingerprint: str | None = None,
    anchor: str | None = None,
) -> Path:
    dest = root / IGNORE_FILE
    dest.parent.mkdir(parents=True, exist_ok=True)
    block = [
        "[[ignore]]",
        f'rule = "{_escape(rule)}"',
    ]
    if gate:
        block.append(f'gate = "{_escape(gate)}"')
    if path:
        block.append(f'path = "{_escape(path)}"')
    if fingerprint:
        block.append(f'fingerprint = "{_escape(fingerprint)}"')
    if anchor:
        block.append(f'anchor = "{_escape(anchor)}"')
    block.append(f'reason = "{_escape(reason)}"')
    if owner:
        block.append(f'owner = "{_escape(owner)}"')
    if days is not None:
        expires = (datetime.now(UTC) + timedelta(days=max(1, days))).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        block.append(f'expires = "{expires}"')
    block.append("")
    existing = (
        dest.read_text(encoding="utf-8")
        if dest.is_file()
        else "# codesheriff ignore overrides\n\n"
    )
    if existing and not existing.endswith("\n"):
        existing += "\n"
    dest.write_text(existing + "\n".join(block), encoding="utf-8")
    return dest


def _inline_reason(path: Path, line: int, rule: str, gate: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    if line < 1 or line > len(lines):
        return None
    current = IGNORE_RE.search(lines[line - 1])
    if current and (current.group(1) or "").lower() != "file":
        target = (current.group(2) or "*").strip()
        if _rule_matches(target, rule, gate):
            return f"ignored via quality:ignore {target}"
    if line >= 2:
        previous = IGNORE_RE.search(lines[line - 2])
        if previous and (previous.group(1) or "").lower() == "next-line":
            target = (previous.group(2) or "*").strip()
            if _rule_matches(target, rule, gate):
                return f"ignored via quality:ignore-next-line {target}"
    return None


def _file_header_ignore(path: Path, rule: str, gate: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]
    except OSError:
        return None
    for text in lines:
        match = IGNORE_RE.search(text)
        if not match:
            continue
        scope = (match.group(1) or "").lower()
        target = (match.group(2) or "*").strip()
        if scope == "file" and _rule_matches(target, rule, gate):
            return f"ignored via quality:ignore-file {target}"
        # File-level missing-tests / timing accepts a bare ignore in the header.
        if (
            not match.group(1)
            and _rule_matches(target, rule, gate)
            and rule
            in {
                "missing-tests",
                "untested-change",
                "timing-regression",
            }
        ):
            return f"ignored via quality:ignore {target}"
    return None


def _rule_matches(target: str, rule: str, gate: str) -> bool:
    if not target or target == "*":
        return True
    if target == rule or target == f"{gate}:{rule}":
        return True
    return target.endswith(":*") and target.split(":", 1)[0] == gate


def _path_match(posix: str, pattern: str) -> bool:
    if posix == pattern:
        return True
    return glob_match(posix, pattern) or glob_match(posix, pattern.lstrip("./"))


def suppression_summary(results: list[GateResult]) -> dict[str, Any]:
    """Count findings silenced this run, grouped by gate.

    ``apply_ignores`` records each silenced finding in ``result.evidence`` so
    the report can show exactly what a green check waived.
    """
    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for result in results:
        if not isinstance(result.evidence, dict):
            continue
        for row in result.evidence.get("suppressed", []) or []:
            if not isinstance(row, dict):
                continue
            gate = str(row.get("gate") or result.name)
            counts[gate] = counts.get(gate, 0) + 1
            items.append(row)
    return {"total": len(items), "by_gate": counts, "items": items}


def find_suppression_rule(root: Path, finding_id: str) -> IgnoreRule | None:
    """Return the ignore rule whose fingerprint matches a last-run finding id."""
    if not finding_id:
        return None
    return next(
        (
            rule
            for rule in load_ignore_rules(root, include_expired=True)
            if rule.fingerprint == finding_id
        ),
        None,
    )


def remove_suppression(root: Path, finding_id: str) -> bool:
    """Delete the ``[[ignore]]`` block whose fingerprint matches, if any."""
    dest = ignore_path(root)
    if not dest.is_file():
        return False
    lines = dest.read_text(encoding="utf-8").splitlines()
    blocks: list[list[str]] = []
    current: list[str] | None = None
    preamble: list[str] = []
    for line in lines:
        if line.strip().startswith("[["):
            if current is not None:
                blocks.append(current)
            current = [line]
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    if current is not None:
        blocks.append(current)
    needle = f'fingerprint = "{_escape(finding_id)}"'
    removed = False
    kept: list[list[str]] = []
    for block in blocks:
        if not removed and needle in [text.strip() for text in block]:
            removed = True
            continue
        kept.append(block)
    if not removed:
        return False
    out = preamble
    for block in kept:
        out.extend(block)
    text = "\n".join(out).rstrip("\n") + "\n"
    dest.write_text(text, encoding="utf-8")
    return True


def _opt_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
