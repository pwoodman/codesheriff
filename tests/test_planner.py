from quality_gates.change_manifest import Change, ChangeManifest
from quality_gates.config import QualityConfig
from quality_gates.planner import build_plan, write_plan


def test_plan_has_prerequisites_and_change_inputs() -> None:
    manifest = ChangeManifest(
        "available",
        "base",
        "target",
        "tree",
        "digest",
        (Change("modified", "src/app.py"),),
    )
    plan = build_plan(
        ["security", "compile", "ui"], QualityConfig(fail_on=["compile"]), manifest
    )

    assert plan[1].prerequisites == ("security",)
    assert plan[2].prerequisites == ("compile",)
    assert plan[1].required is True
    assert plan[0].inputs == ("src/app.py",)


def test_plan_is_persisted_for_reports(tmp_path) -> None:
    path = write_plan(tmp_path, build_plan(["lint"], QualityConfig(), None))

    assert '"name": "lint"' in path.read_text(encoding="utf-8")


def test_render_plan_explains_selection_and_exclusions() -> None:
    from quality_gates.planner import render_plan

    plan = build_plan(["lint"], QualityConfig(), None)
    rendered = render_plan(plan)

    assert "Quality execution plan:" in rendered
    assert "- lint: required;" in rendered
    assert "Excluded gates:" in rendered
    assert "Summary:" in rendered


def test_plan_topologically_orders_prerequisites() -> None:
    # ui needs compile, compile needs security
    plan = build_plan(["ui", "compile", "security"], QualityConfig(), None)
    selected_names = [t.name for t in plan if t.status == "selected"]
    assert selected_names == ["security", "compile", "ui"]


def test_plan_reports_reused_evidence_from_existing_artifact(tmp_path) -> None:
    reports_dir = tmp_path / ".quality-reports"
    reports_dir.mkdir()
    (reports_dir / "lint.json").write_text("{}", encoding="utf-8")

    plan = build_plan(["lint"], QualityConfig(), None, root=tmp_path)

    assert plan[0].reused_evidence == "existing lint artifact present"


def test_plan_excluded_task_has_none_permission_and_reason() -> None:
    plan = build_plan(["lint"], QualityConfig(), None, all_gates=["lint", "coverage"])
    excluded = next(t for t in plan if t.status == "excluded")

    assert excluded.name == "coverage"
    assert excluded.permission == "none"
    assert excluded.exclusion_reason == (
        "not applicable to changed surface or excluded by configuration"
    )
