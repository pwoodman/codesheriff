"""Oracle stall detection and merge-certificate lifecycle states."""

from __future__ import annotations

import json
from pathlib import Path

from quality_gates.certificate import build_certificate
from quality_gates.models import Finding, GateResult
from quality_gates.oracle import (
    remaining_from_results,
    render_prompt,
    reset_stall,
    track_stall,
)


def _failing_payload() -> dict:
    finding = Finding(
        gate="lint",
        rule="unused",
        path="a.py",
        line=3,
        severity="error",
        message="unused import",
    )
    result = GateResult(name="lint", status="fail", findings=[finding])
    return remaining_from_results([result])


def test_certificate_state_work_remaining() -> None:
    payload = _failing_payload()
    cert = build_certificate(payload)
    assert cert["ready"] is False
    assert cert["state"] == "work-remaining"
    assert cert["needs_human"] is False


def test_certificate_state_ready() -> None:
    cert = build_certificate({"green": True, "playbook": {"remaining": 0}})
    assert cert["ready"] is True
    assert cert["state"] == "ready"


def test_certificate_state_awaiting_review() -> None:
    cert = build_certificate(
        {"green": False, "playbook": {"remaining": 0}, "review": {"findings": []}}
    )
    assert cert["state"] == "awaiting-review"


def test_certificate_state_needs_human() -> None:
    cert = build_certificate(
        {"green": False, "needs_human": True, "playbook": {"remaining": 1}}
    )
    assert cert["state"] == "needs-human"
    assert cert["ready"] is False


def test_track_stall_flags_after_repeated_next_action(tmp_path: Path) -> None:
    payload = _failing_payload()
    for _ in range(2):
        info = track_stall(tmp_path, payload)
        assert info["needs_human"] is False
    info = track_stall(tmp_path, payload)
    assert info["needs_human"] is True
    assert info["repeats"] == 3
    assert payload["needs_human"] is True
    state = json.loads(
        (tmp_path / ".quality-reports" / "oracle-state.json").read_text()
    )
    assert state["repeats"] == 3


def test_track_stall_resets_when_blockers_change(tmp_path: Path) -> None:
    payload = _failing_payload()
    for _ in range(3):
        track_stall(tmp_path, payload)
    payload["blocking"] = []
    info = track_stall(tmp_path, payload)
    assert info["repeats"] == 1
    assert info["needs_human"] is False


def test_reset_stall_clears_counter(tmp_path: Path) -> None:
    payload = _failing_payload()
    track_stall(tmp_path, payload)
    assert (tmp_path / ".quality-reports" / "oracle-state.json").is_file()
    reset_stall(tmp_path)
    assert not (tmp_path / ".quality-reports" / "oracle-state.json").exists()


def test_stall_prompt_tells_the_agent_to_stop() -> None:
    payload = _failing_payload()
    payload["needs_human"] = True
    payload["stall"] = {"reason": "repeated", "repeats": 4}
    prompt = render_prompt(payload)
    assert "STOP" in prompt
    assert "codesheriff oracle --reset-stall" in prompt
    assert "codesheriff suppress" in prompt


def test_green_certificate_ignores_stall(tmp_path: Path) -> None:
    payload = remaining_from_results([GateResult(name="lint", status="pass")])
    payload["playbook"] = {"remaining": 0}
    track_stall(tmp_path, payload)
    cert = build_certificate(payload)
    assert cert["ready"] is True
    assert cert["state"] == "ready"
