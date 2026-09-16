from __future__ import annotations

import json
import subprocess
from pathlib import Path

from quality_gates.ci_plan import risk_decision, select_change_gates
from quality_gates.cli import main
from quality_gates.commands.guard import scan_text
from quality_gates.commands.replay import _select


def test_guard_detects_secret() -> None:
    findings = scan_text('API_KEY = "abcdef1234567890"\n', "app.py")
    assert [item.rule for item in findings] == ["hardcoded-secret"]


def test_guard_detects_conflict_and_token() -> None:
    text = "<<<<<<< HEAD\ntoken = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789'\n"
    rules = {item.rule for item in scan_text(text, "app.py")}
    assert "merge-conflict" in rules
    assert "github-token" in rules


def test_guard_ignores_examples() -> None:
    assert scan_text('API_KEY = "your-example-key-here"\n', "docs.py") == []


def test_guard_cli_blocks_on_staged_secret(tmp_path: Path, capsys) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "s@s"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "s"], cwd=tmp_path, check=True)
    (tmp_path / "app.py").write_text('PASSWORD = "hunter2hunter2"\n', encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    code = main(["--root", str(tmp_path), "guard"])
    out = capsys.readouterr().out
    assert code == 1
    assert "commit stopped" in out


def test_guard_cli_clean_tree(tmp_path: Path, capsys) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "safe.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "safe.py"], cwd=tmp_path, check=True)
    assert main(["--root", str(tmp_path), "guard"]) == 0
    assert "clean" in capsys.readouterr().out


def test_guard_json_exit_and_shape(tmp_path: Path, capsys) -> None:
    (tmp_path / "a.py").write_text('SECRET = "0123456789abcdef"\n', encoding="utf-8")
    code = main(["--root", str(tmp_path), "--json", "guard", "a.py"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["blocked"] is True
    assert payload["findings"][0]["rule"] == "hardcoded-secret"


def test_risk_decision_widens_for_auth_change() -> None:
    gates, notes = risk_decision(
        ["format", "lint"], ["src/auth/session.py"], mode="auto"
    )
    assert "authorization" in gates
    assert any("risk-wide" in note for note in notes)


def test_risk_decision_narrows_without_risk_surface() -> None:
    gates, notes = risk_decision(
        ["format", "lint", "security", "coverage"],
        ["src/util/strings.py"],
        mode="auto",
    )
    assert "coverage" not in gates
    assert "format" in gates
    assert any("risk-narrow" in note for note in notes)


def test_risk_decision_keeps_required_gates() -> None:
    gates, _ = risk_decision(
        ["format", "coverage"],
        ["docs/notes.py"],
        required={"coverage"},
        mode="auto",
    )
    assert "coverage" in gates


def test_risk_decision_off_is_noop() -> None:
    gates, notes = risk_decision(["format", "security"], ["src/auth.py"], mode="off")
    assert gates == ["format", "security"]
    assert notes == []


def test_select_change_gates_still_appends_capabilities() -> None:
    gates = select_change_gates(["format"], ["src/payments/charge.py"])
    assert "resilience" in gates


def test_run_risk_auto_plans_without_running(tmp_path: Path, capsys) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "s@s"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "s"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "src.py").write_text("y = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.py"], cwd=tmp_path, check=True)
    code = main(
        ["--root", str(tmp_path), "run", "--plan", "--risk", "auto", "--base", "HEAD"]
    )
    assert code == 0
    assert "risk-" in capsys.readouterr().out


def test_replay_selects_last_entry() -> None:
    entries = [{"run_id": "run-0001"}, {"run_id": "run-0002"}]

    class Args:
        run_id = None
        last = True

    assert _select(entries, Args())["run_id"] == "run-0002"


def test_replay_selects_by_id() -> None:
    entries = [{"run_id": "run-0001"}, {"run_id": "run-0002"}]

    class Args:
        run_id = "run-0001"
        last = False

    assert _select(entries, Args())["run_id"] == "run-0001"


def test_replay_cli_lists_and_emits(tmp_path: Path, capsys) -> None:
    reports = tmp_path / ".quality-reports"
    reports.mkdir()
    (reports / "history.json").write_text(
        json.dumps(
            [
                {
                    "run_id": "run-0001",
                    "ts": "2024-01-01T00:00:00+00:00",
                    "policy": "adopt",
                    "verdict": "fail",
                    "errors": 2,
                    "warnings": 1,
                    "failed": ["lint"],
                    "gates": ["format", "lint"],
                    "certificate": {
                        "ready": False,
                        "state": "work-remaining",
                        "reason": "blockers remain",
                        "auto_merge": "blocked",
                        "version": "1.0.0",
                        "issued_at": "2024-01-01T00:00:00+00:00",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    assert main(["--root", str(tmp_path), "replay", "--list"]) == 0
    assert "run-0001" in capsys.readouterr().out
    assert main(["--root", str(tmp_path), "replay", "run-0001"]) == 0
    out = capsys.readouterr().out
    assert "Replay run-0001" in out
    assert "lint" in out


def test_replay_missing_history_returns_2(tmp_path: Path, capsys) -> None:
    assert main(["--root", str(tmp_path), "replay"]) == 2
    assert "no run history" in capsys.readouterr().out


def test_certificate_sign_and_verify() -> None:
    from quality_gates.certificate import sign_certificate, verify_certificate

    cert = {"ready": True, "version": "1.0.0", "reason": "ok"}
    signed = sign_certificate(cert, "topsecret")
    assert signed["signature"]["algorithm"] == "hmac-sha256"
    assert verify_certificate(signed, "topsecret") is True
    assert verify_certificate(signed, "wrong") is False
    assert verify_certificate(cert, "topsecret") is False


def test_certify_verify_cli_rejects_wrong_key(tmp_path: Path, capsys) -> None:
    reports = tmp_path / ".quality-reports"
    reports.mkdir()
    (reports / "certificate.json").write_text(
        json.dumps(
            {"ready": True, "signature": {"algorithm": "hmac-sha256", "value": "x"}}
        ),
        encoding="utf-8",
    )
    code = main(["--root", str(tmp_path), "certify", "--verify", "--key", "topsecret"])
    assert code == 1
    assert "INVALID" in capsys.readouterr().out


def test_certify_sign_requires_key(tmp_path: Path, capsys) -> None:
    code = main(["--root", str(tmp_path), "certify", "--sign"])
    assert code == 2
    assert "requires --key" in capsys.readouterr().err
