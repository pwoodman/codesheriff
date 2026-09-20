"""Cover the ``security-audit`` CLI command consumer so the impact graph validates it."""

from __future__ import annotations

import argparse
from pathlib import Path

from quality_gates.commands.security_audit import handle
from quality_gates.config import load_config


def test_handle_ignores_other_commands(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    args = argparse.Namespace(command="scan")
    assert handle(args, tmp_path, config) is None


def test_handle_runs_security_audit_command(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    args = argparse.Namespace(
        command="security-audit", out_dir=None, json=True, classes=None
    )
    code = handle(args, tmp_path, config)
    assert code in (0, None)
