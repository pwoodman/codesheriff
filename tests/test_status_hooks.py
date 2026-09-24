"""CLI `status` and `hooks` commands (status_payload consumers)."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.commands.hooks import handle as hooks_handle
from quality_gates.commands.status import handle as status_handle
from quality_gates.status_payload import hooks_payload, status_payload


def _args(**kw):  # type: ignore[no-untyped-def]
    class _A:
        pass

    a = _A()
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_status_payload_reports_green_flag(tmp_path: Path) -> None:
    payload = status_payload(tmp_path)
    assert isinstance(payload, dict)
    assert "green" in payload
    assert isinstance(payload["green"], bool)


def test_hooks_payload_lists_precommit(tmp_path: Path) -> None:
    (tmp_path / ".pre-commit-config.yaml").write_text(
        "repos:\n  - repo: local\n", encoding="utf-8"
    )
    payload = hooks_payload(tmp_path)
    assert isinstance(payload, dict)
    pre = [h for h in payload["hooks"] if h["type"] == "pre-commit"]
    assert pre and pre[0]["status"] in {"configured", "active"}


def test_hooks_payload_empty_repo(tmp_path: Path) -> None:
    payload = hooks_payload(tmp_path)
    assert payload["hooks"] == []
    assert payload["automations"] == []


def test_status_handle_json_prints_payload(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = status_handle(
        _args(command="status", json=True, verbose=False), tmp_path, config=None
    )
    assert code in {0, 1}
    out = capsys.readouterr().out
    assert json.loads(out)["green"] is False  # no reports yet -> not green


def test_status_handle_console_renders(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = status_handle(
        _args(command="status", json=False, verbose=True), tmp_path, config=None
    )
    assert code in {0, 1}
    assert "Status:" in capsys.readouterr().out


def test_status_handle_ignores_other_commands(tmp_path: Path) -> None:
    assert status_handle(_args(command="run"), tmp_path, config=None) is None


def test_hooks_handle_list_json(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = hooks_handle(
        _args(
            command="hooks",
            action="list",
            json=True,
            list_all=False,
        ),
        tmp_path,
        config=None,
    )
    assert code in {0, 1}
    assert isinstance(json.loads(capsys.readouterr().out), (list, dict))


def test_hooks_handle_ignores_other_commands(tmp_path: Path) -> None:
    assert (
        hooks_handle(
            _args(command="status", action="list", json=False, list_all=False),
            tmp_path,
            config=None,
        )
        is None
    )
