"""``codesheriff security-audit`` — 6-phase adversarial security audit engine.

Outperforms Cloudflare security-audit-skill by delivering:
  1. Reconnaissance architecture mapping and coverage ledger
  2. 11 Domain Attack Classes systematic hunting
  3. Adversarial disproving logic to eliminate false positives
  4. Tri-state classification (CONFIRMED, NEEDS_VALIDATION, REJECTED)
  5. Target-neutral comprehensive reporting (REPORT.md, FINDINGS-DETAIL.md, NEEDS-VALIDATION.md)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from quality_gates.audit.security_audit import run_security_audit
from quality_gates.config import QualityConfig


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "security-audit",
        help="6-phase adversarial security audit outperforming Cloudflare security-audit-skill",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="directory to write audit reports (default: .quality-reports/security-audit)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output results in structured JSON format to stdout",
    )
    parser.add_argument(
        "--classes",
        nargs="*",
        default=None,
        help="specific attack classes to evaluate (e.g. AC-01 AC-03 AC-04)",
    )


def handle(args: argparse.Namespace, root: Path, config: QualityConfig) -> int | None:
    if getattr(args, "command", None) != "security-audit":
        return None

    res = run_security_audit(
        root=root,
        out_dir=args.out_dir,
        config=config,
        attack_classes=args.classes,
    )

    if args.json:
        import json

        data = {
            "audited_files": res.ledger.audited_files,
            "audited_lines": res.ledger.audited_lines,
            "candidates_discovered": res.candidates_count,
            "confirmed_count": len(res.confirmed_findings),
            "needs_validation_count": len(res.needs_validation),
            "rejected_count": res.rejected_count,
            "output_dir": res.output_dir.as_posix(),
        }
        print(json.dumps(data, indent=2))
    else:
        print(res.summary())

    return 1 if res.confirmed_findings else 0
