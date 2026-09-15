import hashlib
import hmac
import json

from quality_gates.cli import main
from quality_gates.config import QualityConfig
from quality_gates.planner import build_plan
from quality_gates.product import (
    cache_provenance,
    select_monorepo_targets,
    static_benchmark,
    verify_policy_bundle,
)


def test_policy_bundle_verification_detects_tampering(tmp_path) -> None:
    body = {"version": "2026.1", "policy": {"fail_on": ["security"]}}
    key = "local-test-key"
    signature = hmac.new(
        key.encode(),
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({**body, "signature": signature}), encoding="utf-8")

    assert verify_policy_bundle(path, key)["valid"] is True
    path.write_text(
        json.dumps({**body, "version": "tampered", "signature": signature}),
        encoding="utf-8",
    )
    assert verify_policy_bundle(path, key)["valid"] is False


def test_time_budget_defers_only_advisory_tasks() -> None:
    plan = build_plan(
        ["security", "compile", "review"],
        QualityConfig(fail_on=["security", "compile"]),
        None,
        time_budget_seconds=1,
    )

    assert [item.status for item in plan[:2]] == ["selected", "selected"]
    assert next(item for item in plan if item.name == "review").status == "deferred"
    assert "estimate" in __import__(
        "quality_gates.planner", fromlist=["render_plan"]
    ).render_plan(plan)


def test_cache_provenance_and_static_benchmark_never_execute(tmp_path) -> None:
    cache = tmp_path / "cache"
    (cache / "aa").mkdir(parents=True)
    (cache / "aa" / "entry.json").write_text("{}", encoding="utf-8")

    assert (
        cache_provenance(cache, offline=True)["provenance"]
        == "local deterministic result cache"
    )
    payload = static_benchmark([tmp_path], QualityConfig())
    assert payload["execution"] == "none"
    assert payload["repositories"][0]["trust"] == "untrusted-static-only"


def test_monorepo_target_selection_uses_existing_workspace_boundaries(tmp_path) -> None:
    package = tmp_path / "api"
    package.mkdir()
    (package / "pyproject.toml").write_text("[project]\nname='api'\n", encoding="utf-8")

    selected = select_monorepo_targets(tmp_path, ["api/app.py"])

    assert selected["execution"] == "selection-only"
    assert selected["targets"] == [{"path": "api", "manifest": "pyproject.toml"}]


def test_cli_trace_redaction_sarif_and_fleet_export(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    reports = tmp_path / ".quality-reports"
    reports.mkdir()
    (reports / "quality-report.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "name": "lint",
                        "status": "pass",
                        "command": ["lint"],
                        "findings": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    secret = tmp_path / "report.json"
    secret.write_text(
        '{"api_key": "secret", "value": "token=hidden"}', encoding="utf-8"
    )

    assert main(["trace", "export"]) == 0
    assert (reports / "agent-trace.json").is_file()
    assert main(["redact", "--input", str(secret)]) == 0
    assert "<redacted>" in capsys.readouterr().out
    assert main(["sarif", "export-baseline"]) == 0
    assert main(["fleet", "export", "--opt-in"]) == 0
    fleet = json.loads((reports / "fleet-metrics.json").read_text(encoding="utf-8"))
    assert all("path" not in item for item in fleet["metrics"])
