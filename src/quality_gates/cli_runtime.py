"""Runtime handlers for the ``codesheriff`` subcommands.

Argument parsing stays in :mod:`quality_gates.cli`; this module owns what each
command actually does. Handlers that need to re-enter the CLI import
``quality_gates.cli.main`` lazily so there is no import cycle.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from quality_gates import gates as gate_runners
from quality_gates.config import QualityConfig
from quality_gates.decision import evaluate
from quality_gates.detect import detect_languages
from quality_gates.evidence import attach_evidence
from quality_gates.models import GateResult
from quality_gates.policy import apply_policy, maybe_comment_pr, write_baseline
from quality_gates.registry import canonical_name
from quality_gates.report import (
    build_digest,
    emit_annotations,
    render_console,
    write_reports,
)


def _cli_main(argv: list[str]) -> int:
    from quality_gates.cli import main

    return main(argv)


def _fix(root: Path, *, apply_patches: bool, as_json: bool) -> int:
    from quality_gates.autofix import run_autofix
    from quality_gates.oracle import remaining_from_reports, render_prompt

    payload = run_autofix(root, apply_patches=apply_patches)
    remaining = remaining_from_reports(root)
    remaining["autofix"] = payload
    if as_json:
        print(json.dumps(remaining, indent=2))
    else:
        for note in payload.get("applied") or []:
            print(note)
        print(render_prompt(remaining))
    return 0 if remaining.get("green") else 1


def _certify(
    root: Path,
    *,
    as_json: bool,
    sign: bool = False,
    verify: bool = False,
    key: str | None = None,
) -> int:
    from quality_gates.oracle import remaining_from_reports

    payload = remaining_from_reports(root)
    certificate = payload.get("certificate") or {}
    signing_key = key or os.environ.get("SHERIFF_CERT_KEY", "")
    if verify:
        from quality_gates.certificate import verify_certificate

        if not signing_key:
            print("verify requires --key or SHERIFF_CERT_KEY", file=sys.stderr)
            return 2
        ok = verify_certificate(certificate, signing_key)
        print(
            json.dumps({"valid": ok}, indent=2)
            if as_json
            else (
                "certificate signature: valid"
                if ok
                else "certificate signature: INVALID"
            )
        )
        return 0 if ok else 1
    if sign:
        from quality_gates.certificate import (
            sign_certificate,
            write_certificate,
        )

        if not signing_key:
            print("sign requires --key or SHERIFF_CERT_KEY", file=sys.stderr)
            return 2
        signed = sign_certificate(certificate, signing_key)
        payload["certificate"] = signed
        write_certificate(root, payload)
        certificate = signed
    if as_json:
        print(json.dumps(certificate, indent=2))
    else:
        from quality_gates.certificate import render_certificate

        print(render_certificate(certificate))
    return 0 if certificate.get("ready") else 1


def _apply_one(root: Path, finding_id: str | None, *, as_json: bool) -> int:
    from quality_gates.models import Finding
    from quality_gates.oracle import finding_from_reports
    from quality_gates.review.apply import apply_and_verify

    packed = finding_from_reports(root, finding_id)
    row = packed.get("finding")
    if not isinstance(row, dict):
        if as_json:
            print(json.dumps(packed, indent=2))
        else:
            print(packed.get("error") or "no finding")
        return 1
    finding = Finding(
        gate=str(row.get("gate") or "review"),
        message=str(row.get("message") or ""),
        path=row.get("path"),
        line=row.get("line") if isinstance(row.get("line"), int) else None,
        rule=row.get("rule"),
        patch=row.get("patch"),
        suggestion=row.get("suggestion"),
        verify=row.get("verify"),
    )
    verified = apply_and_verify(root, finding)
    verified["id"] = row.get("id")
    if as_json:
        print(json.dumps(verified, indent=2))
    else:
        print(verified.get("status") or verified)
        if verified.get("next"):
            print(verified["next"])
    return 0 if verified.get("resolved") else 1


def _oracle(root: Path, args: argparse.Namespace) -> int:
    from quality_gates.oracle import (
        remaining_from_reports,
        render_prompt,
        reset_stall,
    )

    if getattr(args, "reset_stall", False):
        reset_stall(root)
    if args.run:
        argv = ["--root", str(root), "run"]
        if args.only:
            argv.extend(["--only", args.only])
        if args.skip:
            argv.extend(["--skip", args.skip])
        if args.full:
            argv.append("--full")
        if getattr(args, "base", None):
            argv.extend(["--base", args.base])
        _cli_main(argv)
    payload = remaining_from_reports(root)
    if args.prompt:
        print(render_prompt(payload))
    else:
        print(json.dumps(payload, indent=2))
    if payload.get("needs_human"):
        return 2
    return 0 if payload.get("green") else 1


def _eval(root: Path, args: argparse.Namespace) -> int:
    from quality_gates.review.bench import run_heuristic_suite
    from quality_gates.review.evalbench import (
        run_sheriff_suite,
        write_sheriff_scorecard,
    )
    from quality_gates.review.external_eval import (
        download_martian,
        llm_eval_enabled,
        macroscope_reconstructed,
    )

    suite = args.eval_suite
    payload: dict[str, object] = {}
    if suite in {"reviewbench", "all"}:
        payload["reviewbench"] = run_heuristic_suite()
    if suite in {"sheriffbench", "all"}:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            sheriff = run_sheriff_suite(tmp=Path(tmp))
        write_sheriff_scorecard(root, sheriff)
        payload["sheriffbench"] = sheriff
    if suite in {"martian", "all"}:
        if args.download or suite == "martian":
            payload["martian"] = download_martian(root, force=args.download)
        else:
            payload["martian"] = {
                "skipped": "pass --download to fetch MIT golden comments",
                "url": "https://github.com/withmartian/code-review-benchmark",
            }
    if suite in {"macroscope", "all"}:
        payload["macroscope"] = macroscope_reconstructed()
    if args.llm and not llm_eval_enabled():
        payload["llm"] = {
            "skipped": True,
            "reason": "set QUALITY_REVIEW_EVAL=1 and ANTHROPIC_API_KEY or OPENAI_API_KEY",
        }
    print(json.dumps(payload, indent=2))
    dest = root / ".quality-reports" / "eval" / "SCORECARD.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_eval_markdown(payload), encoding="utf-8")
    bench = payload.get("reviewbench")
    if isinstance(bench, dict) and bench.get("failed"):
        return 1
    sheriff = payload.get("sheriffbench")
    if isinstance(sheriff, dict) and sheriff.get("failed"):
        return 1
    if args.llm and not llm_eval_enabled():
        return 2
    return 0


def _eval_markdown(payload: dict[str, object]) -> str:
    lines = ["# Review eval scorecard", ""]
    bench = payload.get("reviewbench")
    if isinstance(bench, dict):
        lines += [
            "## ReviewBench (heuristic)",
            "",
            f"- cases: {bench.get('cases')}",
            f"- recall: {bench.get('recall')}",
            f"- hard-negative pass: {bench.get('hard_negative_pass')}",
            f"- failed: {', '.join(bench.get('failed') or []) or 'none'}",
            "",
        ]
    sheriff = payload.get("sheriffbench")
    if isinstance(sheriff, dict):
        from quality_gates.review.evalbench import render_sheriff_scorecard

        lines += [render_sheriff_scorecard(sheriff), ""]
    martian = payload.get("martian")
    if isinstance(martian, dict):
        lines += [
            "## Martian CRB",
            "",
            f"- {martian.get('citation') or martian.get('url') or ''}",
            f"- PRs: {martian.get('prs', martian.get('skipped', ''))}",
            "",
        ]
    macro = payload.get("macroscope")
    if isinstance(macro, dict):
        lines += ["## Macroscope reconstructed sample", "", f"- {macro.get('id')}", ""]
    lines.append(
        "Source: `codesheriff eval`. Settings are the heuristic suite defaults."
    )
    lines.append("")
    return "\n".join(lines)


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _resolve_languages(
    root: Path,
    config: QualityConfig,
    explicit: list[str] | None,
    files: list[Path] | None,
) -> list[str]:
    if explicit:
        return [canonical_name(item) or item for item in explicit]
    return detect_languages(root, config, files)["languages"]


def _print_detect(info: dict[str, list[str]], as_json: bool) -> int:
    if as_json:
        print(json.dumps(info))
    else:
        langs = ", ".join(info["languages"]) or "(none)"
        tools = ", ".join(info["toolchains"]) or "(none)"
        print(f"languages:  {langs}")
        print(f"toolchains: {tools}")
    return 0


def _emit(
    results: list[GateResult],
    root: Path,
    config: QualityConfig,
    as_json: bool,
    fail_on: list[str],
) -> int:
    from quality_gates.findings_artifact import (
        reconcile_last_findings,
        rotate_and_persist,
    )
    from quality_gates.ignore import apply_ignores

    results, policy = apply_policy(results, root, config)
    leftover = reconcile_last_findings(root, results)
    if leftover:
        apply_ignores(results, root)
    rotate_and_persist(root, results)
    for result in results:
        if not result.evidence:
            attach_evidence(result, root, config)
    maybe_comment_pr(results, root, config, policy)
    emit_annotations(results)
    digest = build_digest(
        results, policy=policy, report_dir=root / ".quality-reports", root=root
    )
    write_reports(digest, root / ".quality-reports", policy=policy)
    if as_json:
        print(json.dumps(digest.to_dict(), indent=2))
    else:
        print(render_console(digest))
    # ``fail_on`` is the selected run's required contract for one-command and
    # CI execution. The evaluator also rejects failed scanners without findings.
    required = [item.name for item in results if item.name in fail_on]
    return 0 if evaluate(results, required).approved else 1


def _watch(root: Path, config: QualityConfig, *, interval: float) -> int:
    from quality_gates.watch import notify, watch_loop

    def _rerun() -> None:
        print("change detected — codesheriff run --skip review", flush=True)
        code = _cli_main(["--root", str(root), "run", "--skip", "review"])
        _watch_oracle(root, code)

    print(f"watching {root} every {interval}s (Ctrl-C to stop)", flush=True)
    notify("Sheriff", f"watching {root}")
    try:
        return watch_loop(root, config, _rerun, interval=interval)
    except KeyboardInterrupt:
        return 0


def _watch_oracle(root: Path, code: int | None) -> None:
    """Surface the oracle's single next action after a watched run.

    Watch mode is where the loop is tightest, so it should tell the developer
    the one thing to do next rather than leaving them to re-read the report.
    """
    from quality_gates.oracle import remaining_from_reports, render_prompt
    from quality_gates.watch import notify

    try:
        payload = remaining_from_reports(root)
    except (OSError, ValueError):
        return
    if payload.get("green"):
        notify("Sheriff", "green — all blocking gates pass")
        print("oracle: green, nothing to do", flush=True)
        return
    instruction = (payload.get("playbook") or {}).get("next") or {}
    text = str(instruction.get("instruction") or payload.get("next") or "").strip()
    if text:
        print(f"oracle next: {text}", flush=True)
        notify("Sheriff", text)
    if payload.get("needs_human"):
        print(render_prompt(payload), flush=True)


def _onboard(root: Path, args: argparse.Namespace) -> int:
    from quality_gates.onboard import init_repo

    code = init_repo(
        root,
        policy=args.init_policy,
        org=args.org,
        source=args.source,
        pin=args.pin,
        vendor_cli=args.vendor_cli,
        require_check=bool(args.require_check),
        force=args.force,
        hooks=bool(getattr(args, "hooks", False)),
        agents=bool(getattr(args, "agents", False)),
        auto_merge=bool(getattr(args, "auto_merge", False)),
        review_provider=getattr(args, "ai", "auto"),
        dry_run=bool(getattr(args, "dry_run", False)),
    )
    if getattr(args, "dry_run", False):
        return code
    if getattr(args, "run", False):
        print("Running first gates and writing a baseline...")
        run_code = _cli_main(["--root", str(root), "run", "--skip", "review"])
        base_code = _cli_main(["--root", str(root), "baseline"])
        if run_code not in {0, 1}:
            code = run_code
        elif base_code != 0:
            code = base_code
    if args.command == "setup":
        print("\nThe Code Sheriff is ready.")
        print("Next:")
        print("  1. Review the generated files.")
        print("  2. Commit them to the repository.")
        print("  3. Open a pull request to see the check run.")
        print(
            "Files: sheriff.toml, .github/workflows/quality.yml, .sheriff-baseline.json"
        )
        if getattr(args, "hooks", False):
            print("Include .pre-commit-config.yaml if it was just written.")
        if getattr(args, "agents", False):
            print(
                "Include .cursor/mcp.json, .mcp.json, "
                ".cursor/rules/the-code-sheriff.mdc, and the Code Sheriff skill."
            )
            print(
                "Put `quality` on PATH (`uv tool install git+https://github.com/pwoodman/the-code-sheriff.git`) so MCP can spawn."
            )
        if getattr(args, "auto_merge", False):
            print("GitHub auto-merge: land PRs when `codesheriff certify` is ready.")
        print(
            "Need to troubleshoot? Run `codesheriff doctor` or "
            "`codesheriff report` after the first check."
        )
    else:
        print("Next: codesheriff run --skip review && codesheriff baseline")
    if args.command == "setup" and getattr(args, "app", False):
        from quality_gates.github_app import cli_github_app

        register = argparse.Namespace(
            app_command="register",
            host="127.0.0.1",
            port=8787,
            webhook_url="",
            org=args.org,
            name="The Code Sheriff",
            public=True,
            no_open=False,
            no_init=True,
        )
        app_code = cli_github_app(register)
        return app_code or code
    return code


def _baseline(root: Path, config: QualityConfig, *, ratchet: bool) -> int:
    report = root / ".quality-reports" / "quality-report.json"
    if not report.is_file():
        print(
            "no .quality-reports/quality-report.json — running coverage + audit first"
        )
        results = [
            gate_runners.run_coverage(root, config),
            gate_runners.run_audit(root, config),
        ]
        write_reports(results, root / ".quality-reports")
    path = write_baseline(root, config, ratchet=ratchet)
    print(f"wrote {path.relative_to(root)}" + (" (ratchet)" if ratchet else ""))
    print("Commit this file so PRs fail only on new issues, not the existing backlog.")
    return 0
