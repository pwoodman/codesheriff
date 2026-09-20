"""Full 6-Phase Adversarial Security Audit Engine.

Beats Cloudflare security-audit-skill by delivering:
  1. Reconnaissance & Architecture Mapping (architecture.md)
  2. Systematic Hunting across 11 Domain Attack Classes
  3. Adversarial Disprover (Sanitizers & Defense Analysis)
  4. Structured Output & Dynamic Coverage Ledger (coverage-ledger.json)
  5. Independent Verification & Grounded Citation Checks
  6. Target-Neutral Comprehensive Reporting (REPORT.md, FINDINGS-DETAIL.md, NEEDS-VALIDATION.md)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from quality_gates.audit.attack_classes import (
    CandidateFinding,
    scan_file_for_attack_classes,
)
from quality_gates.audit.cloudflare_reports import write_all_audit_artifacts
from quality_gates.audit.recon import (
    CoverageLedger,
    build_coverage_ledger,
    generate_architecture_map,
    write_recon_artifacts,
)
from quality_gates.audit.verifier import VerifiedFinding, verify_candidates
from quality_gates.config import QualityConfig


@dataclass
class SecurityAuditResult:
    ledger: CoverageLedger
    candidates_count: int
    confirmed_findings: list[VerifiedFinding]
    needs_validation: list[VerifiedFinding]
    rejected_count: int
    output_dir: Path

    def summary(self) -> str:
        lines = [
            "============================================================",
            " 6-PHASE ADVERSARIAL SECURITY AUDIT SUMMARY",
            "============================================================",
            f" Scope: {self.ledger.audited_files} files ({self.ledger.audited_lines:,} LOC)",
            f" Candidate findings discovered: {self.candidates_count}",
            f" Confirmed vulnerabilities:      {len(self.confirmed_findings)}",
            f" Needs architectural validation: {len(self.needs_validation)}",
            f" Disproven false positives:      {self.rejected_count}",
            "------------------------------------------------------------",
            f" Artifacts written to: {self.output_dir.as_posix()}",
            "   - architecture.md",
            "   - coverage-ledger.json",
            "   - REPORT.md",
            "   - FINDINGS-DETAIL.md",
            "   - NEEDS-VALIDATION.md",
            "   - security-audit.json",
            "============================================================",
        ]
        return "\n".join(lines)


def run_security_audit(
    root: Path,
    out_dir: Path | None = None,
    config: QualityConfig | None = None,
    attack_classes: list[str] | None = None,
) -> SecurityAuditResult:
    """Execute complete 6-phase adversarial security audit."""
    target_out = out_dir or (root / ".quality-reports" / "security-audit")

    # Phase 1: Reconnaissance
    ledger = build_coverage_ledger(root, config, attack_classes)
    arch_md = generate_architecture_map(root, ledger, config)

    # Phase 2: Systematic Hunting across 11 Attack Classes
    all_candidates: list[CandidateFinding] = []
    for rel_path, entry in ledger.files.items():
        file_path = root / rel_path
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            entry.status = "skipped"
            continue

        file_candidates = scan_file_for_attack_classes(
            rel_path, content, attack_classes
        )
        all_candidates.extend(file_candidates)

        entry.status = "audited"
        entry.attack_classes_evaluated = ledger.attack_classes
        ledger.audited_files += 1
        ledger.audited_lines += entry.lines

    # Phase 3 & 5: Adversarial Disproving and Grounding Verification
    verified = verify_candidates(all_candidates, root)

    confirmed = [f for f in verified if f.verdict == "CONFIRMED"]
    needs_val = [f for f in verified if f.verdict == "NEEDS_VALIDATION"]
    rejected = [f for f in verified if f.verdict == "REJECTED"]

    # Phase 4 & 6: Structured Output & Comprehensive Reporting
    write_recon_artifacts(target_out, ledger, arch_md)
    write_all_audit_artifacts(target_out, root, ledger, verified)

    return SecurityAuditResult(
        ledger=ledger,
        candidates_count=len(all_candidates),
        confirmed_findings=confirmed,
        needs_validation=needs_val,
        rejected_count=len(rejected),
        output_dir=target_out,
    )
