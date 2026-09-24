"""Brand migration and consistency: no user-visible stale 'quality' docs."""

from __future__ import annotations

import re
from pathlib import Path

import quality_gates.cli_ext as cli_ext
import quality_gates.commands.migrate as migrate_cmd
import quality_gates.commands.why as why_cmd
from quality_gates.agent_loop import write_agent_integrations

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src" / "quality_gates"

# The v2 config key is `[sheriff]`; legacy reads pull `[quality]` for compat.
CONFIG_KEY_RE = re.compile(r"^\[quality\]", re.M)


def _args(**overrides):
    class Args:
        command = "migrate"
        dry_run = False
        json = False

    for key, value in overrides.items():
        setattr(Args, key, value)
    return Args()


def test_migrate_renames_config_and_data_dir(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text("[quality]\n", encoding="utf-8")
    legacy_dir = tmp_path / ".quality"
    legacy_dir.mkdir()
    (legacy_dir / "ignore.toml").write_text("[[ignore]]\n", encoding="utf-8")

    assert migrate_cmd.handle(_args(), tmp_path, None) == 0
    assert (tmp_path / "sheriff.toml").is_file()
    assert not (tmp_path / "quality.toml").exists()
    assert (tmp_path / ".sheriff" / "ignore.toml").is_file()
    assert not legacy_dir.exists()


def test_migrate_rewrites_legacy_markers(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("x = 1  # quality:ignore\n", encoding="utf-8")
    assert migrate_cmd.handle(_args(), tmp_path, None) == 0
    assert "codesheriff:ignore" in source.read_text(encoding="utf-8")
    assert "quality:ignore" not in source.read_text(encoding="utf-8")


def test_migrate_dry_run_changes_nothing(tmp_path: Path) -> None:
    (tmp_path / "quality.toml").write_text("[quality]\n", encoding="utf-8")
    source = tmp_path / "app.py"
    source.write_text("x = 1  # quality:ignore\n", encoding="utf-8")
    assert migrate_cmd.handle(_args(dry_run=True), tmp_path, None) == 0
    assert (tmp_path / "quality.toml").is_file()
    assert not (tmp_path / "sheriff.toml").exists()
    assert "quality:ignore" in source.read_text(encoding="utf-8")


def test_no_stale_quality_command_strings_in_source() -> None:
    """User-visible guidance must say `codesheriff`, not the retired `quality` CLI."""
    offender = re.compile(
        r"(?<![A-Za-z0-9_-])quality (?:fix|oracle|run|report|ignore|doctor|onboard|review)\b"
    )
    hits: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if offender.search(text):
            hits.append(path.relative_to(REPO_ROOT).as_posix())
    assert hits == [], f"stale `quality <cmd>` strings in: {hits}"


def test_no_stale_quality_paths_in_user_facing_strings() -> None:
    """`quality.toml` / `.quality/` / `quality:ignore` in guidance confuses users."""
    allowed = {
        # Compat shims intentionally mention the legacy names.
        "quality_gates/ignore.py",
        "quality_gates/review/feedback.py",
        "quality_gates/config.py",
        "quality_gates/paths.py",
        "quality_gates/commands/migrate.py",
        # Tests and docs inside the package legitimately reference both.
        "quality_gates/reviewer_coverage.py",
    }
    hits: list[str] = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC.parent).as_posix()
        if rel in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if CONFIG_KEY_RE.search(text):
            hits.append(f"{rel}: `[quality]` config key")
    assert hits == [], f"legacy config key in: {hits}"


def test_rewrite_argv_expands_admin_group() -> None:
    from quality_gates.cli import _rewrite_argv

    argv, group = _rewrite_argv(["admin", "baseline", "--json"])
    assert argv == ["baseline", "--json"]
    assert group == "admin"


def test_rewrite_argv_expands_debug_group() -> None:
    from quality_gates.cli import _rewrite_argv

    argv, group = _rewrite_argv(["debug", "doctor"])
    assert argv == ["doctor"]
    assert group == "debug"


def test_rewrite_argv_group_only_has_no_command() -> None:
    from quality_gates.cli import _rewrite_argv

    argv, group = _rewrite_argv(["admin"])
    assert argv == []
    assert group == "admin"


def test_rewrite_argv_deprecated_alias(capsys) -> None:
    from quality_gates.cli import _rewrite_argv

    argv, group = _rewrite_argv(["check", "--base", "HEAD"])
    assert argv == ["review", "--base", "HEAD"]
    assert group is None
    assert "deprecated" in capsys.readouterr().err


def test_rewrite_argv_passthrough() -> None:
    from quality_gates.cli import _rewrite_argv

    argv, group = _rewrite_argv(["run", "--json"])
    assert argv == ["run", "--json"]
    assert group is None


def test_main_group_only_prints_help(capsys) -> None:
    from quality_gates.cli import main

    assert main(["admin"]) == 0
    out = capsys.readouterr().out
    assert "codesheriff admin" in out
    assert "codesheriff baseline" in out


def test_main_admin_run_forwards(capsys) -> None:
    from quality_gates.cli import main

    rc = main(["admin", "version"])
    assert rc in (0, 1)


def test_main_deprecated_check_alias(capsys) -> None:
    import pytest

    from quality_gates.cli import main

    with pytest.raises(SystemExit) as excinfo:
        main(["check", "--help"])
    assert excinfo.value.code == 0
    assert "deprecated" in capsys.readouterr().err


def test_cli_ext_registers_and_dispatches_new_commands(tmp_path: Path) -> None:
    """`cli_ext` is the seam new commands plug into; exercise load + dispatch."""
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    cli_ext.register_parsers(sub)
    names = set(sub.choices)
    assert {"why", "replay", "guard", "migrate"} <= names

    # A foreign command must fall through every handler (returns None).
    parsed = parser.parse_args(["why", "--json"])
    assert cli_ext.dispatch(parsed, tmp_path, None) == 2


def test_why_explains_last_run_finding(tmp_path: Path) -> None:
    """`why` reads the last-run artifact and explains a finding with no re-scan."""
    import argparse
    import json

    report = tmp_path / ".quality-reports"
    report.mkdir(parents=True)
    (report / "findings-last.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "findings": [
                    {
                        "gate": "dead",
                        "rule": "unused-code",
                        "path": "src/a.py",
                        "line": 3,
                        "message": "unused variable 'x'",
                        "severity": "error",
                        "fingerprint": "abc123",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    cli_ext.register_parsers(sub)
    args = parser.parse_args(["why", "abc123", "--json"])
    assert why_cmd.handle(args, tmp_path, None) == 0
    out = _capture(lambda: cli_ext.dispatch(args, tmp_path, None))
    payload = json.loads(out)
    assert payload and payload[0]["rule"] == "unused-code"


def _capture(fn) -> str:
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        fn()
    return buffer.getvalue()


def test_agent_loop_writes_loop_files(tmp_path: Path) -> None:
    """The agent-loop surfaces are the contract that keeps agents on the oracle."""
    written = write_agent_integrations(tmp_path)
    assert written
    rule = (tmp_path / ".cursor" / "rules" / "the-code-sheriff.mdc").read_text(
        encoding="utf-8"
    )
    assert "codesheriff:agent-loop" in rule
    assert "codesheriff oracle" in rule
    skill = (
        tmp_path / ".cursor" / "skills" / "the-code-sheriff" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "codesheriff oracle" in skill
    assert "certificate" in skill
    assert not (tmp_path / ".cursor" / "mcp.json").exists()
    assert not (tmp_path / ".mcp.json").exists()
