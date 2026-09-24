from __future__ import annotations

import os
from pathlib import Path

from quality_gates.config import QualityConfig, load_config
from quality_gates.impact_graph import (
    build_graph,
    load_cached_graph,
    save_cached_graph,
)
from quality_gates.models import Finding


def _pkg(root: Path) -> None:
    pkg = root / "pkg"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "core.py").write_text("VALUE = 1\n", encoding="utf-8")
    (pkg / "service.py").write_text("from .core import VALUE\n", encoding="utf-8")


def test_p1_graph_cache_roundtrip(tmp_path: Path) -> None:
    _pkg(tmp_path)
    config = QualityConfig()
    graph = build_graph(tmp_path, config, use_cache=False)
    saved = save_cached_graph(tmp_path, graph, config)
    assert saved is not None
    assert (tmp_path / ".quality-reports" / "graph.json").is_file()
    loaded = load_cached_graph(tmp_path, config)
    assert loaded is not None
    assert loaded.files == graph.files
    assert dict(loaded.imports) == dict(graph.imports)


def test_p1_graph_cache_opt_out(tmp_path: Path) -> None:
    _pkg(tmp_path)
    (tmp_path / "quality.toml").write_text(
        "[quality.impact]\ncache = false\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    graph = build_graph(tmp_path, config, use_cache=False)
    assert save_cached_graph(tmp_path, graph, config) is None
    assert load_cached_graph(tmp_path, config) is None


def test_p1_graph_cache_no_git_ok(tmp_path: Path, monkeypatch) -> None:
    _pkg(tmp_path)
    monkeypatch.setattr("quality_gates.impact_graph._git_head", lambda _root: None)
    config = QualityConfig()
    graph = build_graph(tmp_path, config, use_cache=False)
    assert save_cached_graph(tmp_path, graph, config) is not None
    assert load_cached_graph(tmp_path, config) is not None


def test_p1_graph_cache_invalidates_on_change(tmp_path: Path) -> None:
    _pkg(tmp_path)
    config = QualityConfig()
    graph = build_graph(tmp_path, config, use_cache=False)
    save_cached_graph(tmp_path, graph, config)
    target = tmp_path / "pkg" / "core.py"
    target.write_text("VALUE = 2\nEXTRA = 3\n", encoding="utf-8")
    os.utime(target, (9999999999, 9999999999))
    assert load_cached_graph(tmp_path, config) is None


def test_p1_prove_never_fails(tmp_path: Path) -> None:
    from quality_gates.gates.review import attempt_prove, run_review

    findings = [
        Finding(
            gate="review",
            severity="error",
            path="pkg/core.py",
            line=1,
            rule="logic",
            message="boom",
            suggestion="fix it",
        )
    ]
    notes = attempt_prove(tmp_path, findings)
    assert any("prove_attempt" in note for note in notes)
    assert (tmp_path / ".quality-reports" / "prove.md").is_file()
    # empty findings also safe
    notes2 = attempt_prove(tmp_path, [])
    assert any("prove_attempt" in note or "prove:" in note for note in notes2)
    # run_review wrapper keeps backward compat and never fails on prove
    config = QualityConfig(ai_review="never")
    result = run_review(tmp_path, config, ["python"], base="HEAD", post=False)
    assert result.status == "skip"
    result2 = run_review(
        tmp_path, config, ["python"], base="HEAD", post=False, prove=True
    )
    assert result2.status == "skip"
    assert any("prove" in note for note in result2.notes)


def test_p1_light_flag_sets_budgets(tmp_path: Path, monkeypatch) -> None:
    from quality_gates import cli as cli_mod

    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_run_review(root, config, languages, **kwargs):
        seen["related"] = config.review_related_files
        seen["rounds"] = config.review_tool_rounds
        seen["passes"] = config.review_passes
        seen["light"] = getattr(config, "light", False)
        seen["prove"] = kwargs.get("prove", False)
        from quality_gates.models import GateResult

        return GateResult(name="review", status="pass")

    monkeypatch.setattr(cli_mod, "run_review", fake_run_review)
    monkeypatch.setattr(cli_mod, "_emit", lambda *a, **k: 0)
    assert cli_mod.main(["review", "--light", "--prove", "--base", "HEAD"]) == 0
    assert seen["related"] == 2
    assert seen["rounds"] == 1
    assert seen["passes"] == 1
    assert seen["light"] is True
    assert seen["prove"] is True


def test_p1_override_parse() -> None:
    from quality_gates.review.context import parse_pr_override

    body = (
        "hello\n```quality-override\nrelated_files: 2\ntool_rounds: 1\n"
        "passes: 1\nmode: single\n```\nbye"
    )
    data = parse_pr_override(body)
    assert data["related_files"] == 2
    assert data["tool_rounds"] == 1
    assert data["passes"] == 1
    assert data["mode"] == "single"
    assert parse_pr_override("no fence here") == {}
    assert parse_pr_override(None) == {}


def test_p1_light_skips_ensemble(tmp_path: Path) -> None:
    from quality_gates.review.llm import run_llm_review

    calls = {"n": 0}

    class Client:
        name = "scripted"

        def complete(self, messages, *, temperature=0.2, max_tokens=2400):
            calls["n"] += 1
            return '{"action":"submit","summary":"ok","findings":[]}'

    config = QualityConfig(review_passes=5)
    config.light = True
    summary, _findings, mode = run_llm_review(
        Client(), "prompt", mode="ensemble", config=config, root=tmp_path, diff=""
    )
    assert mode == "single"
    assert calls["n"] == 1
    assert summary == "ok"
