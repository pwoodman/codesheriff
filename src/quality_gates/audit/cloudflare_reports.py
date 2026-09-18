"""Phase 4 & Phase 6: Target-Neutral Comprehensive Security Audit Reporting.

Generates professional, platform-neutral audit artifacts:
  - REPORT.md: Executive summary, methodology, severity matrix, and attack class coverage.
  - FINDINGS-DETAIL.md: Full vulnerability dossiers with proof-of-exploit and remediation patches.
  - NEEDS-VALIDATION.md: Architectural questions for candidate flaws requiring human validation.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from quality_gates.audit.recon import CoverageLedger
from quality_gates.audit.verifier import VerifiedFinding


def generate_executive_report(
    root: Path,
    ledger: CoverageLedger,
    verified_findings: list[VerifiedFinding],
) -> str:
    """Generate target-neutral REPORT.md markdown content."""
    confirmed = [f for f in verified_findings if f.verdict == "CONFIRMED"]
    needs_val = [f for f in verified_findings if f.verdict == "NEEDS_VALIDATION"]
    rejected = [f for f in verified_findings if f.verdict == "REJECTED"]

    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for vf in confirmed:
        sev = vf.candidate.severity.lower()
        sev_counts[sev] = sev_counts.get(sev, 0) + 1

    lines = [
        "# Security Audit & Vulnerability Assessment Report",
        "",
        "## Executive Summary",
        f"- **Audited Target**: `{root.name}`",
        "- **Audit Depth**: 6-Phase Adversarial Verification Harness",
        f"- **Files Scanned**: {ledger.audited_files}/{ledger.total_files} ({ledger.audited_lines:,} lines of code)",
        f"- **Confirmed Vulnerabilities**: {len(confirmed)}",
        f"- **Needs Validation (Human in the Loop)**: {len(needs_val)}",
        f"- **False Positives Disproven & Rejected**: {len(rejected)}",
        "",
        "## Severity Breakdown (Confirmed Findings)",
        "| Severity | Count | SLA / Action Required |",
        "|---|---|---|",
        f"| 🔴 Critical | {sev_counts['critical']} | Immediate emergency hotfix required |",
        f"| 🟠 High | {sev_counts['high']} | Remediation required within current sprint |",
        f"| 🟡 Medium | {sev_counts['medium']} | Schedule for upcoming release |",
        f"| ⚪ Low | {sev_counts['low']} | Hardening and defensive defense-in-depth |",
        "",
        "## Domain Attack Class Coverage (11 Classes)",
        "| ID | Attack Class Name | Files Evaluated | Findings Confirmed |",
        "|---|---|---|---|",
    ]

    for ac in ledger.attack_classes:
        acid = ac.split(":")[0]
        acname = ac.split(":")[1] if ":" in ac else ac
        conf_count = len([f for f in confirmed if f.candidate.attack_class_id == acid])
        lines.append(f"| {acid} | {acname} | {ledger.audited_files} | {conf_count} |")

    lines.extend(
        [
            "",
            "## Methodology: Adversarial Disproving",
            "All candidate patterns were subjected to adversarial disproving logic:",
            "1. **Defensive Invariant Validation**: Analyzed surrounding context for sanitizers, type constraints, and safe APIs.",
            "2. **Grounding Verification**: Validated file existence, line bounds, and symbol anchors on disk.",
            "3. **Tri-State Classification**: Partitioned into Confirmed exploits, Developer Inquiries (Needs Validation), and Disproven False Positives.",
            "",
            "See `FINDINGS-DETAIL.md` for comprehensive vulnerability dossiers and remediation code.",
            "See `NEEDS-VALIDATION.md` for architectural questions requiring developer review.",
        ]
    )
    return "\n".join(lines)


def generate_findings_detail(
    confirmed_findings: list[VerifiedFinding],
) -> str:
    """Generate FINDINGS-DETAIL.md containing in-depth dossiers for all confirmed flaws."""
    if not confirmed_findings:
        return "# Detailed Security Findings\n\nNo confirmed vulnerabilities detected across audited targets."

    lines = [
        "# Detailed Security Findings & Proof-of-Exploit Dossiers",
        "",
        f"Total Confirmed Vulnerabilities: {len(confirmed_findings)}",
        "",
    ]

    for idx, vf in enumerate(confirmed_findings, 1):
        c = vf.candidate
        sev_emoji = {
            "critical": "🔴 CRITICAL",
            "high": "🟠 HIGH",
            "medium": "🟡 MEDIUM",
            "low": "⚪ LOW",
        }.get(c.severity.lower(), "⚪ INFO")

        lines.extend(
            [
                f"## #{idx}. {c.title}",
                f"- **Severity**: {sev_emoji}",
                f"- **Attack Class**: `{c.attack_class_id}: {c.attack_class_name}`",
                f"- **Classification**: `{c.cwe}`",
                f"- **Location**: `{c.path}:{c.line}`",
                "",
                "### Vulnerability Description",
                c.description,
                "",
                "### Evidence Snippet",
                "```python",
                c.evidence_snippet,
                "```",
                "",
                "### Proof of Exploit / Attack Scenario",
                vf.proof_of_exploit or c.exploit_scenario,
                "",
                "### Remediation Guidance",
                c.suggested_fix,
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines)


def generate_needs_validation(
    needs_val_findings: list[VerifiedFinding],
) -> str:
    """Generate NEEDS-VALIDATION.md for ambiguous findings requiring human verification."""
    if not needs_val_findings:
        return "# Needs Validation\n\nNo security findings require additional architectural validation."

    lines = [
        "# Candidate Flaws Requiring Human / Architectural Validation",
        "",
        "The following observations exhibit potentially vulnerable code patterns,",
        "but may be mitigated by upstream infrastructure (API gateways, auth middleware, or RLS).",
        "",
    ]

    for idx, vf in enumerate(needs_val_findings, 1):
        c = vf.candidate
        lines.extend(
            [
                f"### Inquiry #{idx}: {c.title} ({c.path}:{c.line})",
                f"- **Attack Class**: `{c.attack_class_id}: {c.attack_class_name}`",
                f"- **Observed Pattern**: {c.description}",
                f"- **Validation Question**: {vf.validation_question}",
                "",
            ]
        )
    return "\n".join(lines)


def write_all_audit_artifacts(
    out_dir: Path,
    root: Path,
    ledger: CoverageLedger,
    verified_findings: list[VerifiedFinding],
) -> dict[str, str]:
    """Write REPORT.md, FINDINGS-DETAIL.md, and NEEDS-VALIDATION.md to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    confirmed = [f for f in verified_findings if f.verdict == "CONFIRMED"]
    needs_val = [f for f in verified_findings if f.verdict == "NEEDS_VALIDATION"]

    report_md = generate_executive_report(root, ledger, verified_findings)
    detail_md = generate_findings_detail(confirmed)
    val_md = generate_needs_validation(needs_val)

    (out_dir / "REPORT.md").write_text(report_md, encoding="utf-8")
    (out_dir / "FINDINGS-DETAIL.md").write_text(detail_md, encoding="utf-8")
    (out_dir / "NEEDS-VALIDATION.md").write_text(val_md, encoding="utf-8")

    # Also save structured JSON
    structured = {
        "confirmed": [
            {**asdict(vf.candidate), "proof_of_exploit": vf.proof_of_exploit}
            for vf in confirmed
        ],
        "needs_validation": [
            {**asdict(vf.candidate), "validation_question": vf.validation_question}
            for vf in needs_val
        ],
        "rejected_count": len(
            [f for f in verified_findings if f.verdict == "REJECTED"]
        ),
    }
    (out_dir / "security-audit.json").write_text(
        json.dumps(structured, indent=2), encoding="utf-8"
    )

    return {
        "report_md": report_md,
        "detail_md": detail_md,
        "needs_validation_md": val_md,
    }
