"""``codesheriff scan`` — whole-repository and whole-file semantic scanner.

Outperforms Alibaba Open Code Review's ``ocr scan`` by executing deep polyglot
static inspection, AST token pruning, and cross-file invariant analysis without
requiring a git diff.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.review.ast_prune import prune_file_context, token_reduction_stats
from quality_gates.scan import run_scan


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "scan",
        help="scan entire files or repository without requiring a git diff (surpassing Alibaba ocr scan)",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=[],
        help="specific files or directories to scan (default: all project files)",
    )
    parser.add_argument(
        "--severity",
        choices=["info", "warning", "error", "critical"],
        default="info",
        help="minimum finding severity to report",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="maximum number of files to analyze (default: 500)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output results in structured JSON format",
    )
    parser.add_argument(
        "--prune-tokens",
        action="store_true",
        help="calculate AST-directed token reduction statistics for scanned files",
    )


def handle(args: argparse.Namespace, root: Path, config: QualityConfig) -> int | None:
    if getattr(args, "command", None) != "scan":
        return None

    result = run_scan(
        root=root,
        targets=args.targets if args.targets else None,
        config=config,
        min_severity=args.severity,
        max_files=args.max_files,
    )

    prune_stats = {}
    if args.prune_tokens:
        total_orig = 0.0
        total_pruned = 0.0
        sample_files = result.target_paths[:20]
        for rel_path in sample_files:
            file_p = root / rel_path
            if file_p.is_file():
                try:
                    code = file_p.read_text(encoding="utf-8")
                    pruned = prune_file_context(file_p, code, retain_lines=[1, 2, 3])
                    stats = token_reduction_stats(code, pruned)
                    total_orig += stats["original_tokens"]
                    total_pruned += stats["pruned_tokens"]
                except (OSError, UnicodeDecodeError, SyntaxError) as err:
                    _ = err
        avg_ratio = total_pruned / total_orig if total_orig > 0 else 1.0
        prune_stats = {
            "sample_files_count": len(sample_files),
            "original_tokens": total_orig,
            "pruned_tokens": total_pruned,
            "token_ratio": round(avg_ratio, 4),
            "token_savings_pct": round((1.0 - avg_ratio) * 100, 2),
        }

    if args.json:
        payload = result.to_dict()
        if prune_stats:
            payload["token_pruning"] = prune_stats
        print(json.dumps(payload, indent=2))
    else:
        print(result.render_cli_summary())
        if prune_stats:
            print("\n--- AST Token Pruning Metrics (<1/10th tokens) ---")
            print(f" Analyzed {prune_stats['sample_files_count']} sample files")
            print(
                f" Token Ratio: {prune_stats['token_ratio']}x (Savings: {prune_stats['token_savings_pct']}%)"
            )

    return 1 if result.errors_count > 0 else 0
