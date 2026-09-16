"""Phase 2: dashboard, VCS provider seam, fleet rollup, blob links, watch notify."""

from __future__ import annotations

import contextlib
import json
import socket
import threading
import urllib.request
from pathlib import Path

from quality_gates.cli import main
from quality_gates.dashboard import render_dashboard, suppression_audit, triage
from quality_gates.models import Finding
from quality_gates.product import fleet_summary, render_fleet_markdown
from quality_gates.report_html import render_html
from quality_gates.vcs import (
    CheckOutcome,
    GitHubProvider,
    PullRef,
    RepoRef,
    current_provider,
    provider_for,
    split_repo,
)


def _digest(**kwargs):
    from quality_gates.models import GateResult
    from quality_gates.report import build_digest

    results = [
        GateResult(
            name="review",
            status="fail" if kwargs.get("findings") else "pass",
            findings=kwargs.get("findings", []),
        )
    ]
    return build_digest(results, policy="default")


def test_split_repo_forms() -> None:
    assert split_repo("acme/widgets") == ("acme", "widgets")
    assert split_repo("https://github.com/acme/widgets") == ("acme", "widgets")
    assert split_repo("widgets") == ("", "widgets")


def test_provider_for_known_and_stub() -> None:
    assert provider_for("github").name == "github"
    stub = provider_for("gitlab")
    assert stub.name == "gitlab"
    pull = PullRef(RepoRef("github.com", "a", "b"), 1, "sha")
    assert stub.post_comment(pull, "hi") == CheckOutcome(
        state="gitlab", detail="gitlab provider not implemented"
    )
    assert stub.blob_url(pull, "x.py", 3) == ""


def test_provider_for_unknown_raises() -> None:
    try:
        provider_for("mercurial")
    except ValueError as exc:
        assert "unknown VCS provider" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_current_provider_defaults_to_github() -> None:
    assert current_provider("nope").name == "github"


def test_github_blob_url() -> None:
    provider = GitHubProvider()
    pull = PullRef(RepoRef("https://github.com", "acme", "widgets"), 7, "deadbeef")
    url = provider.blob_url(pull, "src/app.py", 12)
    assert url.endswith("/acme/widgets/blob/deadbeef/src/app.py#L12")


def test_github_pull_from_env_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert GitHubProvider().pull_from_env() is None


def test_report_html_blob_links(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widgets")
    monkeypatch.setenv("GITHUB_SHA", "cafe1234")
    digest = _digest(
        findings=[Finding(gate="review", message="boom", path="src/a.py", line=9)]
    )
    page = render_html(digest)
    assert "/acme/widgets/blob/cafe1234/src/a.py#L9" in page
    assert "class='loc'" in page


def test_report_html_without_ci_has_no_links(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    digest = _digest(
        findings=[Finding(gate="review", message="boom", path="src/a.py", line=9)]
    )
    page = render_html(digest)
    assert "blob/" not in page


def test_dashboard_renders_state_and_audit(tmp_path: Path) -> None:
    reports = tmp_path / ".quality-reports"
    reports.mkdir()
    (reports / "review.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "fingerprint": "fp1",
                        "severity": "error",
                        "path": "a.py",
                        "line": 1,
                        "message": "bad",
                        "rule": "r",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (reports / "history.json").write_text(
        json.dumps([{"run_id": "run-0001", "verdict": "fail", "errors": 1}]),
        encoding="utf-8",
    )
    (reports / "cost.json").write_text(
        json.dumps({"results": [{"name": "lint", "duration_ms": 120}]}),
        encoding="utf-8",
    )
    from quality_gates.platform import api_state

    page = render_dashboard(tmp_path, api_state(tmp_path), suppression_audit(tmp_path))
    assert "<!DOCTYPE html>" in page
    assert "Suppression audit" in page
    assert "Gate timings" in page
    assert "lint" in page
    assert "triage('suppress','fp1')" in page


def test_triage_suppress_and_unsuppress(tmp_path: Path) -> None:
    reports = tmp_path / ".quality-reports"
    reports.mkdir()
    (reports / "findings-last.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "fingerprint": "abc",
                        "gate": "review",
                        "rule": "r",
                        "path": "a.py",
                        "line": 4,
                        "message": "bad",
                        "severity": "error",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    note = triage(tmp_path, {"action": "suppress", "fingerprint": "abc"})
    assert note["ok"] is True
    assert "suppressed abc" in note["note"]
    assert (tmp_path / ".sheriff" / "ignore.toml").is_file()
    again = triage(tmp_path, {"action": "suppress", "fingerprint": "abc"})
    assert "already suppressed" in again["note"]
    gone = triage(tmp_path, {"action": "unsuppress", "fingerprint": "abc"})
    assert gone["ok"] is True
    assert triage(tmp_path, {"action": "nope", "fingerprint": "abc"})["ok"] is False
    assert triage(tmp_path, {"action": "suppress"})["ok"] is False


def test_serve_dashboard_http(tmp_path: Path) -> None:
    from http.server import ThreadingHTTPServer

    from quality_gates.platform import api_state, serve_api

    reports = tmp_path / ".quality-reports"
    reports.mkdir()
    (reports / "review.json").write_text(json.dumps({"findings": []}), encoding="utf-8")
    # Pick a free port, then run the server in a thread we can stop.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    handler_holder: dict[str, ThreadingHTTPServer] = {}

    real_init = ThreadingHTTPServer.__init__

    def capture_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        real_init(self, *args, **kwargs)
        handler_holder["server"] = self

    original = ThreadingHTTPServer.__init__
    ThreadingHTTPServer.__init__ = capture_init  # type: ignore[method-assign]
    thread = threading.Thread(
        target=serve_api, args=(tmp_path,), kwargs={"port": port}, daemon=True
    )
    thread.start()
    try:
        for _ in range(50):
            if "server" in handler_holder:
                break
            threading.Event().wait(0.05)
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as page:
            body = page.read().decode("utf-8")
            assert "Sheriff" in body
            assert page.headers.get("Content-Type", "").startswith("text/html")
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/findings", timeout=5
        ) as api:
            assert json.loads(api.read().decode("utf-8")) == {"findings": []}
        assert api_state(tmp_path)["findings"] == {"findings": []}
    finally:
        ThreadingHTTPServer.__init__ = original  # type: ignore[method-assign]
        if "server" in handler_holder:
            handler_holder["server"].shutdown()


def test_fleet_summary_and_markdown(tmp_path: Path) -> None:
    for name, errors in (("alpha", 2), ("beta", 0)):
        reports = tmp_path / name / ".quality-reports"
        reports.mkdir(parents=True)
        (reports / "quality-report.json").write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "name": "review",
                            "findings": [{"severity": "error"} for _ in range(errors)],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (reports / "history.json").write_text(
            json.dumps([{"verdict": "fail" if errors else "pass", "errors": errors}]),
            encoding="utf-8",
        )
    summary = fleet_summary(tmp_path)
    assert summary["totals"]["repos"] == 2
    assert summary["totals"]["failing"] == 1
    assert summary["totals"]["errors"] == 2
    text = render_fleet_markdown(summary)
    assert "# Sheriff fleet report" in text
    assert "| alpha |" in text and "| beta |" in text


def test_fleet_report_cli_markdown(tmp_path: Path, capsys) -> None:
    reports = tmp_path / "solo" / ".quality-reports"
    reports.mkdir(parents=True)
    (reports / "quality-report.json").write_text(
        json.dumps({"results": []}), encoding="utf-8"
    )
    code = main(["--root", str(tmp_path), "fleet", "report", "--scan", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "# Sheriff fleet report" in out
    assert "solo" in out


def test_fleet_report_cli_json_stdout(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "--root",
            str(tmp_path),
            "fleet",
            "report",
            "--scan",
            str(tmp_path),
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert json.loads(out)["totals"]["repos"] == 0


def test_watch_notify_is_silent_when_disabled(monkeypatch) -> None:
    from quality_gates.watch import notify

    monkeypatch.setenv("SHERIFF_NO_NOTIFY", "1")
    assert notify("t", "m") is False


def test_watch_loop_reruns_on_change(tmp_path: Path) -> None:
    from quality_gates.config import load_config
    from quality_gates.watch import watch_loop

    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    config = load_config(tmp_path)
    calls: list[int] = []

    def _tick() -> None:
        calls.append(1)

    # A single cycle with unchanged files must not trigger a rerun.
    watch_loop(tmp_path, config, _tick, interval=0.01, cycles=1)
    assert calls == []


def test_github_app_manifest_carries_focus_and_argument() -> None:
    from quality_gates.github_app import _run_job

    job = _run_job(
        repository="acme/widgets",
        sha="abc",
        pr=1,
        installation_id=2,
        base="main",
        fork="false",
        command="explain",
        focus="security",
        argument="why is this safe?",
    )
    assert job is not None
    assert job["command"] == "explain"
    assert job["focus"] == "security"
    assert job["argument"] == "why is this safe?"


def test_review_command_env_is_parsed(monkeypatch) -> None:
    """The engine must read focus/argument, not just treat the command as truthy."""
    import quality_gates.review.engine as engine

    captured: dict[str, object] = {}

    def _fake_prompt(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return "PROMPT"

    monkeypatch.setattr(engine, "_prompt", _fake_prompt)
    monkeypatch.setenv("QUALITY_REVIEW_COMMAND", "explain")
    monkeypatch.setenv("QUALITY_REVIEW_ARGUMENT", "what changed?")
    # Force a diff so the review does not short-circuit before prompting.
    monkeypatch.setattr(
        engine,
        "collect_diff",
        lambda root, base, limit: "diff --git a/a.py b/a.py\n+print(1)\n",
    )
    from quality_gates.config import load_config

    config = load_config(Path("."))
    monkeypatch.setattr(engine, "heuristic_review", lambda *a, **k: [])
    monkeypatch.setattr(engine, "related_files", lambda *a, **k: [])
    monkeypatch.setattr(engine, "active_rules", lambda *a, **k: [])
    with contextlib.suppress(Exception):
        engine.run_review(
            Path("."), config, ["python"], base=None, post=False, prior=None
        )
    assert captured.get("question") == "what changed?"


def test_watch_oracle_surfaces_next_action(tmp_path: Path, capsys) -> None:
    """`watch` must print the oracle's single next action, not just a report."""
    from quality_gates.cli_runtime import _watch_oracle

    _watch_oracle(tmp_path, 1)
    out = capsys.readouterr().out
    assert "oracle" in out.lower() or "green" in out.lower()
