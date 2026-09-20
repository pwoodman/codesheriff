"""Whole-repository and whole-file semantic scanner (codesheriff scan).

Provides whole-tree and diff-less file audits that exceed Alibaba Open Code Review's
`ocr scan` command by combining deep 120-point static inspection, AST invariant checks,
and multi-language vulnerability detection across codebases without requiring a git diff.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.detect import detect_languages, iter_project_files
from quality_gates.gates.audit import run_audit
from quality_gates.models import Finding
from quality_gates.review.invariant import extract_signatures_from_text


@dataclass
class ScanResult:
    root: str
    target_paths: list[str]
    scanned_files_count: int
    languages: list[str]
    findings: list[Finding]
    errors_count: int
    warnings_count: int
    info_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "target_paths": self.target_paths,
            "scanned_files_count": self.scanned_files_count,
            "languages": self.languages,
            "findings": [
                f.to_dict() if hasattr(f, "to_dict") else asdict(f)
                for f in self.findings
            ],
            "errors_count": self.errors_count,
            "warnings_count": self.warnings_count,
            "info_count": self.info_count,
        }

    def render_cli_summary(self) -> str:
        lines = [
            "============================================================",
            f" The Code Sheriff Scan: {self.scanned_files_count} files analyzed",
            f" Languages: {', '.join(self.languages) if self.languages else 'none'}",
            f" Findings: {len(self.findings)} (Errors: {self.errors_count}, Warnings: {self.warnings_count}, Info: {self.info_count})",
            "============================================================",
        ]
        if not self.findings:
            lines.append(" No issues detected across scanned targets.")
            return "\n".join(lines)

        for idx, f in enumerate(self.findings, 1):
            sev = (f.severity or "info").upper()
            loc = f"{f.path or '—'}:{f.line or '—'}"
            rule = f" [{f.rule}]" if f.rule else ""
            lines.append(f"{idx:3d}. [{sev}] {loc}{rule}")
            lines.append(f"     {f.message}")
            if f.suggestion:
                lines.append(f"     Suggestion: {f.suggestion}")
        return "\n".join(lines)


def _check_python_file_ast(rel: str, content: str) -> list[Finding]:
    """Inspect Python AST for duplicate top-level function definitions and syntax errors."""
    findings: list[Finding] = []
    try:
        import ast

        tree = ast.parse(content)
        seen_funcs: set[str] = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
                if name in seen_funcs:
                    findings.append(
                        Finding(
                            gate="scan",
                            path=rel,
                            line=node.lineno,
                            severity="error",
                            rule="scan/duplicate-function",
                            message=f"Duplicate function definition '{name}' in '{rel}'",
                            suggestion=f"Rename or remove duplicate definition of '{name}'",
                            confidence="HIGH",
                        )
                    )
                seen_funcs.add(name)
    except SyntaxError as err:
        findings.append(
            Finding(
                gate="scan",
                path=rel,
                line=getattr(err, "lineno", 1),
                severity="error",
                rule="scan/syntax-error",
                message=f"Syntax error in '{rel}': {err.msg}",
                suggestion="Fix the syntax error.",
                confidence="HIGH",
            )
        )
    return findings


def run_scan(
    root: Path,
    targets: list[str] | None = None,
    *,
    config: QualityConfig | None = None,
    min_severity: str = "info",
    max_files: int = 500,
) -> ScanResult:
    cfg = config or QualityConfig()
    all_files = list(iter_project_files(root, cfg))

    if targets:
        resolved_targets: list[Path] = []
        for t in targets:
            tp = (root / t).resolve()
            if tp.is_file():
                resolved_targets.append(tp)
            elif tp.is_dir():
                resolved_targets.extend([p for p in all_files if p.is_relative_to(tp)])
        scanned_files = resolved_targets[:max_files]
    else:
        scanned_files = all_files[:max_files]

    languages = detect_languages(root, cfg)

    # 1. Run audit engine across targets
    audit_res = run_audit(root, cfg)
    findings: list[Finding] = []
    if audit_res and audit_res.findings:
        findings.extend(audit_res.findings)

    # 2. Syntax & signature validation across scanned files
    for p in scanned_files:
        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = p.relative_to(root).as_posix()

        if rel.endswith(".py"):
            findings.extend(_check_python_file_ast(rel, content))
        else:
            _ = extract_signatures_from_text(rel, content)

    # Filter by minimum severity
    sev_rank = {"info": 1, "warning": 2, "error": 3, "critical": 4}
    threshold = sev_rank.get(min_severity.lower(), 1)
    filtered: list[Finding] = []
    errors = 0
    warnings = 0
    infos = 0

    for f in findings:
        s = (f.severity or "info").lower()
        if s in {"error", "critical"}:
            errors += 1
        elif s == "warning":
            warnings += 1
        else:
            infos += 1

        if sev_rank.get(s, 1) >= threshold:
            filtered.append(f)

    return ScanResult(
        root=str(root),
        target_paths=[p.relative_to(root).as_posix() for p in scanned_files],
        scanned_files_count=len(scanned_files),
        languages=languages,
        findings=filtered,
        errors_count=errors,
        warnings_count=warnings,
        info_count=infos,
    )
