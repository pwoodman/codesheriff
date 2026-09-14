from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.models import GateResult
from quality_gates.result_cache import _decode, cache_key, cached_result


def test_cache_key_changes_when_only_tool_configuration_changes(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    config = tmp_path / "ruff.toml"
    config.write_text("line-length = 88\n", encoding="utf-8")
    options = QualityConfig()

    first = cache_key(tmp_path, options, "python", "lint", (source,), tool=None)
    config.write_text("line-length = 100\n", encoding="utf-8")
    second = cache_key(tmp_path, options, "python", "lint", (source,), tool=None)

    assert first != second


def test_cached_result_preserves_evidence() -> None:
    result = GateResult(
        name="test",
        status="pass",
        evidence={
            "snapshot_digest": "tree-123",
            "config_digest": "config-456",
            "runner": "local",
        },
    )

    restored = _decode(result.to_dict())

    assert restored.evidence == result.evidence


def test_cached_result_reports_deterministic_hit_and_miss(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("QUALITY_GATES_CACHE", str(tmp_path / "cache"))
    calls = 0

    def compute() -> GateResult:
        nonlocal calls
        calls += 1
        return GateResult(name="lint", status="pass")

    args = (
        tmp_path,
        QualityConfig(),
        "python",
        "lint",
        (tmp_path / "app.py",),
    )
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")

    first = cached_result(*args, tool="checker", compute=compute)
    second = cached_result(*args, tool="checker", compute=compute)

    assert first.notes[-1] == "deterministic cache miss"
    assert second.notes[-1] == "deterministic cache hit"
    assert "deterministic cache miss" not in second.notes
    assert calls == 1
