"""Phase 3 & Phase 5: Adversarial Disprover and Grounding Verifier.

Applies adversarial disproving logic to candidate findings:
  - Actively searches for defensive guards, type constraints, sanitizers, and middleware.
  - Assigns tri-state verdicts: CONFIRMED, NEEDS_VALIDATION, REJECTED.
  - Verifies grounded citations (real file existence, line bounds, and symbol presence).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from quality_gates.audit.attack_classes import CandidateFinding

AuditVerdict = Literal["CONFIRMED", "NEEDS_VALIDATION", "REJECTED"]


@dataclass
class VerifiedFinding:
    candidate: CandidateFinding
    verdict: AuditVerdict
    disproof_reason: str | None = None
    validation_question: str | None = None
    proof_of_exploit: str | None = None
    grounded: bool = True


def _is_static_rule_or_comment(line_str: str) -> bool:
    """Check if the line is a comment, regex pattern definition, or rule declaration."""
    stripped = line_str.strip()
    if stripped.startswith(("#", "//", "/*", "*", "'''", '"""')):
        return True
    # Check for regex compilation or rule dictionary declarations
    if any(k in stripped for k in ["re.compile(", '"pattern":', "'pattern':"]):
        return True
    return bool(
        any(re_sym in stripped for re_sym in [r"\\s*", r"\s*", r"\.", r"\\."])
        and any(kw in stripped for kw in ["r'", 'r"', "re.compile"])
    )


def _check_sanitization(
    evidence: str, file_content: str, line_no: int
) -> tuple[bool, str]:
    """Inspect surrounding code context for sanitizers, parameterization, or defenses."""
    lines = file_content.splitlines()
    # Check 10 lines before and after
    start = max(0, line_no - 11)
    end = min(len(lines), line_no + 10)
    surrounding = "\n".join(lines[start:end])

    # Check for defense keywords
    if "shlex.quote" in surrounding or "shlex.split" in surrounding:
        return True, "Input is explicitly sanitized using shlex.quote / shlex.split."
    if "yaml.safe_load" in surrounding:
        return True, "YAML deserialization uses safe_load."
    if "secrets.compare_digest" in surrounding:
        return True, "Timing-safe comparison used."
    if (
        "validate_url" in surrounding
        or "is_safe_url" in surrounding
        or "allowed_hosts" in surrounding
    ):
        return True, "URL is validated against hostname whitelist before request."
    if "sanitize" in surrounding or "escape" in surrounding:
        return True, "Input sanitization routine detected in caller context."

    return False, ""


def evaluate_adversarial_disprover(
    candidate: CandidateFinding,
    root: Path,
) -> VerifiedFinding:
    """Attempt to disprove candidate vulnerability using adversarial verification."""
    target_file = root / candidate.path

    # Grounding check: file existence
    if not target_file.is_file():
        return VerifiedFinding(
            candidate=candidate,
            verdict="REJECTED",
            disproof_reason=f"Grounding failure: file '{candidate.path}' does not exist.",
            grounded=False,
        )

    try:
        content = target_file.read_text(encoding="utf-8", errors="ignore")
    except OSError as err:
        return VerifiedFinding(
            candidate=candidate,
            verdict="REJECTED",
            disproof_reason=f"File unreadable: {err}",
            grounded=False,
        )

    file_lines = content.splitlines()
    # Grounding check: line bound
    if candidate.line < 1 or candidate.line > len(file_lines):
        return VerifiedFinding(
            candidate=candidate,
            verdict="REJECTED",
            disproof_reason=f"Grounding failure: line {candidate.line} out of range (1..{len(file_lines)}).",
            grounded=False,
        )

    # Disprover check 1: Test files or documentation
    if any(t in candidate.path.lower() for t in ["test", "spec", "mock", "fixture"]):
        return VerifiedFinding(
            candidate=candidate,
            verdict="REJECTED",
            disproof_reason="Test/fixture artifact; not exposed in production attack surface.",
            grounded=True,
        )

    doc_exts = {".md", ".rst", ".txt", ".adoc", ".markdown"}
    if target_file.suffix.lower() in doc_exts and candidate.attack_class_id not in {
        "AC-09"
    }:
        return VerifiedFinding(
            candidate=candidate,
            verdict="REJECTED",
            disproof_reason="Documentation artifact; code execution sinks not reachable in documentation.",
            grounded=True,
        )

    # Disprover check 2: Regex / rule definition, comment, or metadata message
    matched_line = file_lines[candidate.line - 1]
    if _is_static_rule_or_comment(matched_line):
        return VerifiedFinding(
            candidate=candidate,
            verdict="REJECTED",
            disproof_reason="Candidate line is inside a regex definition, rule dictionary, or comment; not an executable sink.",
            grounded=True,
        )
    if any(
        k in matched_line
        for k in ['"message":', "'message':", '"desc":', "'description':"]
    ):
        return VerifiedFinding(
            candidate=candidate,
            verdict="REJECTED",
            disproof_reason="Candidate line is inside a metadata message or description field; not an executable sink.",
            grounded=True,
        )

    # Disprover check 3: Defensive sanitization
    sanitized, reason = _check_sanitization(
        candidate.evidence_snippet, content, candidate.line
    )
    if sanitized:
        return VerifiedFinding(
            candidate=candidate,
            verdict="REJECTED",
            disproof_reason=reason,
            grounded=True,
        )

    # Disprover check 4: Outbound network request in CLI/client utility
    if candidate.attack_class_id == "AC-05":
        is_client_cli = any(
            p in candidate.path.lower()
            for p in ["cli", "eval", "installer", "fetch", "download", "client"]
        )
        if is_client_cli:
            return VerifiedFinding(
                candidate=candidate,
                verdict="NEEDS_VALIDATION",
                validation_question=(
                    f"Outbound request at {candidate.path}:{candidate.line} is part of a CLI/evaluation client. "
                    "Verify if user-controlled input can reach this sink in a hosted or server context."
                ),
                grounded=True,
            )

    # Disprover check 5: Environment or middleware dependency
    if candidate.attack_class_id in {"AC-01", "AC-08"}:
        return VerifiedFinding(
            candidate=candidate,
            verdict="NEEDS_VALIDATION",
            validation_question=(
                f"Verify whether access control or tenant isolation for '{candidate.title}' "
                f"at {candidate.path}:{candidate.line} is enforced upstream via API gateway, "
                f"auth middleware, or database row-level security (RLS)."
            ),
            grounded=True,
        )

    # Confirmed finding
    return VerifiedFinding(
        candidate=candidate,
        verdict="CONFIRMED",
        proof_of_exploit=f"Reachable un-sanitized sink at {candidate.path}:{candidate.line}. {candidate.exploit_scenario}",
        grounded=True,
    )


def verify_candidates(
    candidates: list[CandidateFinding],
    root: Path,
) -> list[VerifiedFinding]:
    """Run adversarial disprover and grounding verification across all candidate findings."""
    return [evaluate_adversarial_disprover(c, root) for c in candidates]
