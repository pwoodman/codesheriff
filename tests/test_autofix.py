from __future__ import annotations

from pathlib import Path

from quality_gates.autofix import run_autofix
from quality_gates.certificate import build_certificate, render_certificate
from quality_gates.cli import main
from quality_gates.config import QualityConfig
from quality_gates.models import Finding
from quality_gates.review import apply as apply_module
from quality_gates.review.apply import apply_finding


def test_autofix_formats_python(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x=1\n", encoding="utf-8")
    payload = run_autofix(tmp_path, QualityConfig(), apply_patches=False)
    assert payload["applied"]
    assert payload["next"] == "codesheriff oracle --run"


def test_certify_cli_without_reports(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    code = main(["--json", "certify"])
    assert code == 1
    out = capsys.readouterr().out
    assert "blocked" in out or "ready" in out


def test_certificate_markdown_blocked() -> None:
    text = render_certificate(
        build_certificate({"green": False, "blocking": [{"gate": "lint"}]})
    )
    assert "BLOCKED" in text
    assert "Do not auto-merge" in text


def test_line_fix_rejects_syntax_corruption_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    original = "value = 1\n"
    path.write_text(original, encoding="utf-8")

    status = apply_finding(
        tmp_path,
        Finding(
            gate="lint",
            message="bad fix",
            path="app.py",
            line=1,
            patch="```suggestion\nvalue =\n```",
        ),
    )

    assert status.startswith("patch rejected")
    assert path.read_text(encoding="utf-8") == original


def test_unified_fix_rolls_back_when_a_later_write_fails(
    tmp_path: Path, monkeypatch
) -> None:
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("value = 1\n", encoding="utf-8")
    second.write_text("value = 2\n", encoding="utf-8")
    original_write = Path.write_text
    writes = 0

    def fail_second_write(path: Path, data: str, *args, **kwargs) -> int:
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated disk failure")
        return original_write(path, data, *args, **kwargs)

    monkeypatch.setattr(apply_module.Path, "write_text", fail_second_write)
    status = apply_finding(
        tmp_path,
        Finding(
            gate="lint",
            message="multi-file fix",
            patch=(
                "--- a/first.py\n+++ b/first.py\n"
                "@@\n-value = 1\n+value = 10\n"
                "--- a/second.py\n+++ b/second.py\n"
                "@@\n-value = 2\n+value = 20\n"
            ),
        ),
    )

    assert status.startswith("patch rejected")
    assert first.read_text(encoding="utf-8") == "value = 1\n"
    assert second.read_text(encoding="utf-8") == "value = 2\n"
