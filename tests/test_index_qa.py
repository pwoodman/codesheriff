"""Tests for NL Q&A, agent handoff, and persistent graph features."""

from __future__ import annotations

from pathlib import Path

from quality_gates.config import load_config
from quality_gates.review.index import (
    answer_question,
    build_symbol_index,
    get_agent_handoff_context,
    load_symbol_index,
    search_symbols,
)


def test_build_symbol_index_persists(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "def main():\n    return helper()\n\ndef helper():\n    return 42\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    result = build_symbol_index(tmp_path, config)
    assert result["count"] >= 2
    names = [s["name"] for s in result["symbols"] if s["kind"] == "symbol"]
    assert "main" in names
    assert "helper" in names


def test_build_symbol_index_incremental(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("def foo():\n    pass\n", encoding="utf-8")
    config = load_config(tmp_path)
    result1 = build_symbol_index(tmp_path, config)
    assert result1["count"] >= 1

    (src / "utils.py").write_text("def bar():\n    pass\n", encoding="utf-8")
    result2 = build_symbol_index(tmp_path, config)
    assert result2["count"] >= 2
    assert "src/utils.py" in result2.get("updated_paths", [])


def test_load_symbol_index_empty(tmp_path: Path) -> None:
    index = load_symbol_index(tmp_path)
    assert index["count"] == 0
    assert index["symbols"] == []


def test_search_symbols() -> None:
    index = {
        "symbols": [
            {"name": "main", "path": "app.py", "line": 1, "kind": "symbol"},
            {"name": "helper", "path": "utils.py", "line": 5, "kind": "symbol"},
            {"name": "main_handler", "path": "server.py", "line": 10, "kind": "symbol"},
        ]
    }
    hits = search_symbols(index, "main")
    assert len(hits) == 2
    assert any(s["name"] == "main" for s in hits)
    assert any(s["name"] == "main_handler" for s in hits)


def test_search_symbols_empty() -> None:
    assert search_symbols({"symbols": []}, "foo") == []
    assert search_symbols({"symbols": []}, "") == []


def test_answer_question(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(
        "def authenticate(user, password):\n    return check_creds(user, password)\n",
        encoding="utf-8",
    )
    (src / "routes.py").write_text(
        "from auth import authenticate\n\ndef login():\n    authenticate('admin', 'pass')\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    build_symbol_index(tmp_path, config)
    result = answer_question(tmp_path, "where is authentication handled?")
    assert "symbols_found" in result
    assert "files" in result
    assert "agent_prompt" in result
    assert isinstance(result["context"], list)


def test_get_agent_handoff_context(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text(
        "def process(data):\n    return transform(data)\n",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    build_symbol_index(tmp_path, config)
    context = get_agent_handoff_context(
        tmp_path,
        finding_path="src/app.py",
        finding_rule="unsafe-api",
    )
    assert context["tool"] == "codesheriff"
    assert context["finding_path"] == "src/app.py"
    assert context["finding_rule"] == "unsafe-api"
    assert "prompt" in context
    assert "unsafe-api" in context["prompt"]


def test_get_agent_handoff_context_no_path(tmp_path: Path) -> None:
    context = get_agent_handoff_context(tmp_path)
    assert context["tool"] == "codesheriff"
    assert context["finding_path"] is None
    assert "prompt" in context
