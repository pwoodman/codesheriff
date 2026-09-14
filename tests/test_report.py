from __future__ import annotations

from pathlib import Path

from quality_gates.cli import main
from quality_gates.models import Finding, GateResult
from quality_gates.report import (
    build_digest,
    render_console,
    render_html,
    render_markdown,
    write_reports,
)
from quality_gates.report_cli import print_report
from quality_gates.report_html import render_html as render_html_direct
from quality_gates.report_model import INDUSTRY_COVERAGE
from quality_gates.report_render import render_markdown as render_markdown_direct


def _fail(name: str, message: str, *, path: str = "a.py") -> GateResult:
    return GateResult(
        name=name,
        status="fail",
        findings=[
            Finding(gate=name, rule=f"{name}-1", path=path, line=3, message=message)
        ],
        duration_ms=12,
    )


def test_extracted_report_modules_are_covered() -> None:
    digest = build_digest([])
    assert INDUSTRY_COVERAGE == 80.0
    assert render_html_direct(digest).startswith("<!DOCTYPE html>")
    assert "Quality report" in render_markdown_direct(digest)


def test_digest_includes_performance_issues_and_recs() -> None:
    results = [
        GateResult(
            name="format",
            status="pass",
            notes=["ruff format ok"],
            duration_ms=40,
        ),
        _fail("lint", "unused import"),
        GateResult(
            name="coverage",
            status="pass",
            notes=["line coverage 55.0% (floor 50%), branch 30.0% from coverage.xml"],
            duration_ms=800,
        ),
        GateResult(
            name="dry",
            status="pass",
            notes=["duplication: 0% of tokens"],
            duration_ms=100,
        ),
        GateResult(
            name="audit",
            status="pass",
            notes=["surfaces: ci, deps", "confirmed findings: 0 (0 at fail priority)"],
            duration_ms=50,
        ),
        GateResult(
            name="security",
            status="skip",
            notes=["security scanners skipped"],
            skipped_tools=["gitleaks", "osv-scanner", "semgrep"],
            duration_ms=5,
        ),
    ]
    digest = build_digest(results, policy="enforce")
    assert digest.verdict == "fail"
    assert digest.errors == 1
    assert digest.performance.coverage_line == 55.0
    assert digest.performance.duplication_percent == 0.0
    assert digest.performance.audit_surfaces == ["ci", "deps"]
    titles = [item.title for item in digest.recommendations]
    assert "Fix lint errors" in titles
    assert "Install security scanners" in titles
    assert any("80%" in item.detail for item in digest.recommendations)

    text = render_console(digest)
    assert "Scorecard" in text
    assert "Performance" in text
    assert "Issues" in text
    assert "Recommendations" in text
    assert "unused import" in text
    assert "skip ≠ fail" in text or "skipped" in text
    assert "reason:" in text

    md = render_markdown(digest)
    assert "## Performance" in md
    assert "## Issues" in md
    assert "## Recommendations" in md

    page = render_html(digest)
    assert "<!DOCTYPE html>" in page
    assert "Quality report" in page
    assert "unused import" in page
    assert "<details" in page
    assert "pill fail" in page
    assert "skip means not applicable" in page
    assert "filter-gate" in page
    assert "aria-label='line coverage" in page or "line coverage" in page
    assert "class='bar'" in page or 'class="bar"' in page

    md = render_markdown(digest)
    assert "<details" in md
    assert "Skip reason" in md or "security" in md


def test_write_reports_emits_html_and_json(tmp_path: Path) -> None:
    results = [
        GateResult(name="format", status="pass", duration_ms=9),
        GateResult(name="version", status="pass", duration_ms=4),
    ]
    write_reports(results, tmp_path / ".quality-reports", policy="enforce")
    report_dir = tmp_path / ".quality-reports"
    assert (report_dir / "quality-report.md").is_file()
    assert (report_dir / "quality-report.html").is_file()
    payload = (report_dir / "quality-report.json").read_text(encoding="utf-8")
    assert '"verdict": "pass"' in payload
    assert "recommendations" in payload


def test_quality_report_reprints_last_run(tmp_path: Path, capsys, monkeypatch) -> None:
    results = [_fail("version", "bump required", path="src/app.py")]
    write_reports(results, tmp_path / ".quality-reports", policy="enforce")
    monkeypatch.chdir(tmp_path)
    code = main(["report"])
    assert code == 1
    out = capsys.readouterr().out
    assert "Bump the version" in out
    assert "quality bump auto" in out


def test_quality_report_missing_file_returns_2(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    code = main(["report"])
    assert code == 2
    err = capsys.readouterr().err
    assert "no .quality-reports/quality-report.json" in err


def test_quality_report_formats(tmp_path: Path, capsys, monkeypatch) -> None:
    results = [GateResult(name="format", status="pass", duration_ms=10)]
    write_reports(results, tmp_path / ".quality-reports", policy="enforce")
    monkeypatch.chdir(tmp_path)

    # JSON format
    code_json = main(["report", "--format", "json"])
    assert code_json == 0
    out_json = capsys.readouterr().out
    assert '"verdict": "pass"' in out_json

    # Markdown format
    code_md = main(["report", "--format", "markdown"])
    assert code_md == 0
    out_md = capsys.readouterr().out
    assert "Quality report" in out_md

    # HTML format
    code_html = main(["report", "--format", "html"])
    assert code_html == 0
    out_html = capsys.readouterr().out
    assert "<!DOCTYPE html>" in out_html

    # SARIF format
    code_sarif = main(["report", "--format", "sarif"])
    assert code_sarif == 0
    out_sarif = capsys.readouterr().out
    assert '"$schema"' in out_sarif

    # JUnit format
    code_junit = main(["report", "--format", "junit"])
    assert code_junit == 0
    out_junit = capsys.readouterr().out
    assert "<testsuite" in out_junit


def test_quality_report_diff(tmp_path: Path, capsys, monkeypatch) -> None:
    report_dir = tmp_path / ".quality-reports"
    prev_results = [_fail("lint", "old lint error", path="a.py")]
    write_reports(prev_results, report_dir, policy="enforce")
    # rename to prev
    (report_dir / "quality-report.json").rename(report_dir / "quality-report.prev.json")

    curr_results = [
        _fail("lint", "old lint error", path="a.py"),
        _fail("lint", "new lint error", path="b.py"),
    ]
    write_reports(curr_results, report_dir, policy="enforce")

    monkeypatch.chdir(tmp_path)
    code = main(["report", "--diff", "--format", "json"])
    assert code == 1
    out = capsys.readouterr().out
    assert "new lint error" in out


def test_quality_report_diff_no_previous(tmp_path: Path, capsys, monkeypatch) -> None:
    report_dir = tmp_path / ".quality-reports"
    curr_results = [_fail("lint", "some error", path="b.py")]
    write_reports(curr_results, report_dir, policy="enforce")

    monkeypatch.chdir(tmp_path)
    code = main(["report", "--diff"])
    assert code == 1
    out = capsys.readouterr().out
    assert "no previous findings to diff against; showing full report" in out


def test_print_report_direct(tmp_path: Path, capsys) -> None:
    results = [GateResult(name="format", status="pass", duration_ms=10)]
    write_reports(results, tmp_path / ".quality-reports", policy="enforce")
    code = print_report(tmp_path, fmt="console", as_json=False)
    assert code == 0
    out = capsys.readouterr().out
    assert "Scorecard" in out


def test_observe_recommends_adopt() -> None:
    results = [
        GateResult(
            name="lint",
            status="pass",
            findings=[
                Finding(
                    gate="lint",
                    message="style",
                    severity="warning",
                    path="a.py",
                )
            ],
        )
    ]
    digest = build_digest(results, policy="observe")
    assert any("observe" in item.detail.lower() for item in digest.recommendations)
