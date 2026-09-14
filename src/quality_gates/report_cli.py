from __future__ import annotations

import json
import sys
from pathlib import Path

from quality_gates.report import (
    build_digest,
    filter_new_findings,
    load_results,
    render_console,
    render_html,
    render_junit,
    render_markdown,
    render_sarif,
    write_reports,
)


def print_report(
    root: Path, *, fmt: str, as_json: bool, diff: str | None = None
) -> int:
    report_dir = root / ".quality-reports"
    results, policy = load_results(report_dir)
    if not results:
        print(
            "no .quality-reports/quality-report.json — run `quality run` first",
            file=sys.stderr,
        )
        return 2
    if diff:
        prior_results, _prior_policy = load_results(
            report_dir, "quality-report.prev.json"
        )
        previous = [finding for item in prior_results for finding in item.findings]
        current = [finding for item in results for finding in item.findings]
        if previous:
            kept = set(map(id, filter_new_findings(current, previous)))
            for item in results:
                item.findings = [
                    finding for finding in item.findings if id(finding) in kept
                ]
        else:
            print("no previous findings to diff against; showing full report")
    digest = build_digest(results, policy=policy, report_dir=report_dir)
    write_reports(digest, report_dir, policy=policy)
    if as_json or fmt == "json":
        print(json.dumps(digest.to_dict(), indent=2))
        return 0 if digest.verdict == "pass" else 1
    if fmt == "markdown":
        print(render_markdown(digest), end="")
    elif fmt == "html":
        print(render_html(digest), end="")
    elif fmt == "sarif":
        print(json.dumps(render_sarif(digest), indent=2))
    elif fmt == "junit":
        print(render_junit(digest), end="")
    else:
        print(render_console(digest))
    return 0 if digest.verdict == "pass" else 1
