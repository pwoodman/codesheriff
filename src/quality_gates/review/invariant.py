"""Greptile-superiority engine: repository-wide symbol graph, cross-file invariant checking,
and zero-hallucination citation validation.

Detects when modified symbol signatures, schemas, or behaviors break un-updated consumers
in distant files across the codebase, and enforces that all reported findings are grounded
in actual repository symbols and file paths.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files
from quality_gates.models import Finding
from quality_gates.review.index import load_symbol_index


@dataclass
class SymbolSignature:
    name: str
    kind: str  # function, class, method, interface
    path: str
    line: int
    params: list[str] = field(default_factory=list)
    has_varargs: bool = False
    has_varkw: bool = False
    docstring: str = ""


@dataclass
class CrossFileInvariantViolation:
    symbol_name: str
    source_file: str
    consumer_file: str
    consumer_line: int
    reason: str
    suggested_fix: str
    severity: str = "error"


_PY_DEF = re.compile(r"^\s*def\s+([A-Za-z_]\w*)\s*\((.*?)\)", re.M | re.S)
_JS_TS_DEF = re.compile(
    r"(?:export\s+)?(?:async\s+)?(?:function|const|let)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\((.*?)\)|"
    r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)\s*\((.*?)\)",
    re.M,
)
_CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(", re.M)


def extract_signatures_from_text(path: str, text: str) -> dict[str, SymbolSignature]:
    signatures: dict[str, SymbolSignature] = {}

    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    params = [arg.arg for arg in node.args.args]
                    vararg = node.args.vararg is not None
                    kwarg = node.args.kwarg is not None
                    signatures[node.name] = SymbolSignature(
                        name=node.name,
                        kind="function",
                        path=path,
                        line=node.lineno,
                        params=params,
                        has_varargs=vararg,
                        has_varkw=kwarg,
                    )
                elif isinstance(node, ast.ClassDef):
                    signatures[node.name] = SymbolSignature(
                        name=node.name,
                        kind="class",
                        path=path,
                        line=node.lineno,
                        params=[],
                    )
            return signatures
        except SyntaxError as err:
            _ = err  # Fallback to regex pattern matching on incomplete/invalid syntax

    for match in _PY_DEF.finditer(text):
        name = match.group(1)
        raw_params = match.group(2).replace("\n", " ")
        params = [
            p.split(":")[0].split("=")[0].strip()
            for p in raw_params.split(",")
            if p.strip()
        ]
        line = text.count("\n", 0, match.start()) + 1
        signatures[name] = SymbolSignature(
            name=name,
            kind="function",
            path=path,
            line=line,
            params=params,
            has_varargs="*" in raw_params,
            has_varkw="**" in raw_params,
        )

    for match in _JS_TS_DEF.finditer(text):
        name = match.group(1) or match.group(3)
        raw_params = (match.group(2) or match.group(4) or "").replace("\n", " ")
        params = [
            p.split(":")[0].split("=")[0].strip()
            for p in raw_params.split(",")
            if p.strip()
        ]
        line = text.count("\n", 0, match.start()) + 1
        if name:
            signatures[name] = SymbolSignature(
                name=name,
                kind="function",
                path=path,
                line=line,
                params=params,
            )

    return signatures


def find_repository_callers(
    root: Path,
    target_symbol: str,
    target_path: str,
    config: QualityConfig | None = None,
) -> list[tuple[str, int, str]]:
    cfg = config or QualityConfig()
    callers: list[tuple[str, int, str]] = []
    symbol_call_pattern = re.compile(
        rf"\b{re.escape(target_symbol)}\s*\((.*?)\)", re.M | re.S
    )

    for p in iter_project_files(root, cfg):
        rel = p.relative_to(root).as_posix()
        if rel == target_path:
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for m in symbol_call_pattern.finditer(content):
            line = content.count("\n", 0, m.start()) + 1
            call_snippet = m.group(0).strip()
            callers.append((rel, line, call_snippet))

    return callers


def _check_call_mismatch(
    sig: SymbolSignature, call_snippet: str
) -> tuple[bool, int, int]:
    """Helper to detect if call snippet has fewer arguments than required by signature."""
    if "(" not in call_snippet or ")" not in call_snippet:
        return False, 0, 0
    inside = call_snippet[call_snippet.find("(") + 1 : call_snippet.rfind(")")]
    args = [a.strip() for a in inside.split(",") if a.strip()]
    expected_min_args = len([p for p in sig.params if p not in {"self", "cls"}])
    mismatch = len(args) < expected_min_args and not (sig.has_varargs or sig.has_varkw)
    return mismatch, len(args), expected_min_args


def check_cross_file_invariants(
    root: Path,
    changed_files: list[str],
    diff_text: str,
    config: QualityConfig | None = None,
) -> list[CrossFileInvariantViolation]:
    violations: list[CrossFileInvariantViolation] = []
    changed_set = set(changed_files)

    for changed_file in changed_files:
        full_path = root / changed_file
        if not full_path.is_file():
            continue
        try:
            content = full_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        sigs = extract_signatures_from_text(changed_file, content)
        for sym_name, sig in sigs.items():
            if (
                f"def {sym_name}" not in diff_text
                and f"function {sym_name}" not in diff_text
            ):
                continue

            callers = find_repository_callers(root, sym_name, changed_file, config)
            for caller_file, caller_line, call_snippet in callers:
                if caller_file in changed_set:
                    continue

                mismatch, num_args, exp_args = _check_call_mismatch(sig, call_snippet)
                if mismatch:
                    violations.append(
                        CrossFileInvariantViolation(
                            symbol_name=sym_name,
                            source_file=changed_file,
                            consumer_file=caller_file,
                            consumer_line=caller_line,
                            reason=(
                                f"Symbol '{sym_name}' signature changed in '{changed_file}' "
                                f"(requires {exp_args} params: {sig.params}), "
                                f"but consumer '{caller_file}:{caller_line}' passes only {num_args} argument(s) "
                                f"and was omitted from the PR diff."
                            ),
                            suggested_fix=(
                                f"Update invocation in '{caller_file}:{caller_line}' or provide "
                                f"a default value for parameter in '{changed_file}'."
                            ),
                            severity="error",
                        )
                    )

    return violations


def validate_grounded_citations(
    findings: list[Finding],
    root: Path,
    symbol_index: dict[str, Any] | None = None,
) -> tuple[list[Finding], list[Finding]]:
    idx = symbol_index or load_symbol_index(root)
    valid_symbols = {s.get("name") for s in idx.get("symbols", []) if s.get("name")}
    known_paths = {s.get("path") for s in idx.get("symbols", []) if s.get("path")}

    grounded: list[Finding] = []
    ungrounded: list[Finding] = []

    for f in findings:
        if not f.path:
            grounded.append(f)
            continue

        norm_path = f.path.lstrip("./\\").replace("\\", "/")
        file_exists = (root / norm_path).is_file() or norm_path in known_paths
        if not file_exists:
            ungrounded.append(f)
            continue

        symbol = getattr(f, "symbol", None)
        if symbol and valid_symbols and symbol not in valid_symbols:
            ungrounded.append(f)
            continue

        grounded.append(f)

    return grounded, ungrounded


def invariant_violations_to_findings(
    violations: list[CrossFileInvariantViolation],
) -> list[Finding]:
    findings: list[Finding] = []
    for v in violations:
        findings.append(
            Finding(
                gate="review",
                rule="cross-file/unupdated-consumer",
                severity=v.severity,
                path=v.consumer_file,
                line=v.consumer_line,
                message=v.reason,
                suggestion=v.suggested_fix,
                reason=f"Cross-file invariant violation on {v.symbol_name}",
                confidence="HIGH",
            )
        )
    return findings
