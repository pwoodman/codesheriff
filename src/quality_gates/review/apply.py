"""Apply a finding patch and confirm the fingerprint disappeared."""

from __future__ import annotations

import ast
from pathlib import Path

from quality_gates.models import Finding
from quality_gates.review.context import safe_repo_path
from quality_gates.review.parse import fingerprint


def apply_finding(root: Path, finding: Finding) -> str:
    """Apply `finding.patch` to the working tree. Returns a status string."""
    patch = (finding.patch or "").strip()
    if not patch and (finding.suggestion or "").strip():
        patch = f"```suggestion\n{finding.suggestion.strip()}\n```"
    if not patch:
        return "no patch on this finding"
    if "```suggestion" in patch or not _looks_unified(patch):
        return _apply_line_replacement(root, finding, patch)
    return _apply_unified(root, patch)


def finding_from_row(row: dict[str, object]) -> Finding:
    """Rebuild a Finding from a report artifact row."""
    return Finding(
        gate=str(row.get("gate") or "review"),
        message=str(row.get("message") or ""),
        path=row.get("path"),
        line=row.get("line") if isinstance(row.get("line"), int) else None,
        rule=row.get("rule"),
        patch=row.get("patch"),
        suggestion=row.get("suggestion"),
        verify=row.get("verify"),
    )


def apply_reported_finding(
    root: Path, finding_id: str | None
) -> tuple[dict[str, object] | None, dict[str, object]]:
    """Load a reported finding by id, apply it, and verify the result.

    Returns ``(row, verified)``; ``row`` is ``None`` when the id does not
    resolve, in which case ``verified`` is the packed error payload.
    """
    from quality_gates.oracle import finding_from_reports

    packed = finding_from_reports(root, finding_id)
    row = packed.get("finding")
    if not isinstance(row, dict):
        return None, packed
    verified = apply_and_verify(root, finding_from_row(row))
    verified["id"] = row.get("id")
    return row, verified


def apply_and_check(
    root: Path,
    finding: Finding,
    remaining: list[Finding],
) -> dict[str, object]:
    status = apply_finding(root, finding)
    gone = fingerprint(finding, bucket=1) not in {
        fingerprint(item, bucket=1) for item in remaining
    }
    return {
        "status": status,
        "fingerprint": fingerprint(finding, bucket=1),
        "resolved": gone and status.startswith("applied"),
        "verify": finding.verify or f"quality {finding.gate}",
        "next": (
            f"Re-run `{finding.verify or 'quality ' + finding.gate}` to confirm."
            if status.startswith("applied")
            else status
        ),
    }


def apply_and_verify(
    root: Path, finding: Finding, *, attempts: int = 1
) -> dict[str, object]:
    """Apply one authorized patch and require newly-run verification evidence.

    The fixed state is deliberately unavailable to callers that merely observe a
    missing finding in an old report.  Retries are bounded so an unstable patch
    loop has a visible unresolved outcome.
    """
    attempts = max(1, min(attempts, 3))
    status = apply_finding(root, finding)
    if not status.startswith("applied"):
        return {"status": status, "resolved": False, "attempts": 0, "next": status}
    from quality_gates.cli import main
    from quality_gates.report import load_results
    from quality_gates.review.ledger import mark_verified_fixed

    gate = finding.gate if finding.gate else "review"
    for attempt in range(1, attempts + 1):
        code = main(["--root", str(root), "run", "--changed", "--only", gate])
        results, _policy = load_results(root / ".quality-reports")
        remaining = {
            fingerprint(item, bucket=1)
            for result in results
            for item in result.findings
            if item.severity == "error"
        }
        if code == 0 and fingerprint(finding, bucket=1) not in remaining:
            mark_verified_fixed(root, finding)
            return {
                "status": status,
                "resolved": True,
                "attempts": attempt,
                "verify": f"codesheriff run --changed --only {gate}",
            }
    return {
        "status": status,
        "resolved": False,
        "attempts": attempts,
        "next": "fresh verification did not clear the finding; patch remains unresolved",
    }


def _looks_unified(patch: str) -> bool:
    return patch.startswith(("diff ", "--- ", "@@")) or "\n@@" in patch


def _replacement_body(patch: str) -> str:
    if "```suggestion" in patch:
        rest = patch.split("```suggestion", 1)[-1]
        rest = rest.lstrip("\n")
        end = rest.find("```")
        return rest[:end] if end >= 0 else rest
    if _looks_unified(patch):
        added = [
            line[1:]
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]
        return "\n".join(added)
    return patch


def _apply_line_replacement(root: Path, finding: Finding, patch: str) -> str:
    if not finding.path or not finding.line:
        return "patch needs path and line"
    path = safe_repo_path(root, finding.path)
    if path is None:
        return f"path not in repo: {finding.path}"
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    index = finding.line - 1
    if index < 0 or index >= len(lines):
        return "line out of range"
    body = _replacement_body(patch)
    replacement = body.splitlines()
    ending = "\n" if lines[index].endswith("\n") else ""
    if not replacement:
        lines.pop(index)
    else:
        lines[index] = replacement[0] + (
            ending if not replacement[0].endswith("\n") else ""
        )
        extra = replacement[1:]
        for offset, row in enumerate(extra, start=1):
            lines.insert(index + offset, row + ("" if row.endswith("\n") else "\n"))
    updated = "".join(lines)
    if path.suffix in {".py", ".pyi"}:
        try:
            ast.parse(updated, filename=str(path))
        except SyntaxError as exc:
            return f"patch rejected: syntax error at line {exc.lineno or '?'}"
    if not _parses_for_suffix(path.suffix, updated):
        return (
            f"patch rejected: result is not valid {path.suffix.lstrip('.') or 'file'}"
        )
    try:
        path.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return f"patch rejected: could not write file ({exc})"
    return f"applied line replacement at {finding.path}:{finding.line}"


def _parses_for_suffix(suffix: str, text: str) -> bool:
    """Structured-format guard for non-Python patches (never raises)."""
    lowered = suffix.lower()
    if lowered == ".toml":
        import tomllib

        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return False
    elif lowered == ".json":
        import json as _json

        try:
            _json.loads(text)
        except ValueError:
            return False
    return True


def _apply_unified(root: Path, patch: str) -> str:
    parsed = _parse_unified(patch)
    if not parsed:
        return "unified diff did not match"

    # Validate every hunk against a single in-memory snapshot before changing
    # disk. A stale second file must never leave a successful first file behind.
    updated: dict[Path, str] = {}
    for rel, hunks in parsed.items():
        path = safe_repo_path(root, rel)
        if path is None or not path.is_file():
            return f"unified diff rejected: invalid path {rel}"
        try:
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        except OSError:
            return f"unified diff rejected: could not read {rel}"
        for old, new in hunks:
            old_block = "\n".join(old)
            new_block = "\n".join(new)
            if not old_block:
                return "unified diff rejected: insertion-only hunks need context"
            occurrences = text.count(old_block)
            if occurrences != 1:
                reason = "stale" if occurrences == 0 else "ambiguous"
                return f"unified diff rejected: {reason} hunk in {rel}"
            text = text.replace(old_block, new_block, 1)
        updated[path] = text

    originals = {path: path.read_bytes() for path in updated}
    written: list[Path] = []
    try:
        for path, text in updated.items():
            path.write_text(text, encoding="utf-8")
            written.append(path)
    except OSError:
        for path in written:
            try:
                path.write_bytes(originals[path])
            except OSError:
                return "patch rejected: write failed and rollback failed"
        return "patch rejected: could not write validated patch"
    return f"applied unified diff ({len(updated)} file(s))"


def _parse_unified(patch: str) -> dict[str, list[tuple[list[str], list[str]]]]:
    current: str | None = None
    old: list[str] = []
    new: list[str] = []
    parsed: dict[str, list[tuple[list[str], list[str]]]] = {}

    def finish() -> None:
        if current and (old or new):
            parsed.setdefault(current, []).append((list(old), list(new)))

    for raw in patch.splitlines():
        if raw.startswith("+++ b/"):
            finish()
            current = raw[6:].strip()
            old, new = [], []
        elif raw.startswith("@@"):
            finish()
            old, new = [], []
        elif current is not None:
            if raw.startswith("+") and not raw.startswith("+++"):
                new.append(raw[1:])
            elif raw.startswith("-") and not raw.startswith("---"):
                old.append(raw[1:])
            elif raw.startswith(" "):
                old.append(raw[1:])
                new.append(raw[1:])
    finish()
    return parsed
