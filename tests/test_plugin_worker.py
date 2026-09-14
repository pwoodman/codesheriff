from quality_gates.models import GateResult
from quality_gates.plugin_worker import _result_from_json


def test_plugin_worker_decodes_findings_and_execution_state() -> None:
    result = _result_from_json(
        {
            "name": "example-plugin",
            "status": "fail",
            "exit_state": "errored",
            "notes": ["worker failed safely"],
            "findings": [
                {
                    "gate": "example-plugin",
                    "rule": "plugin-exception",
                    "message": "plugin crashed",
                    "severity": "error",
                    "path": "src/app.py",
                }
            ],
        }
    )

    assert isinstance(result, GateResult)
    assert result.status == "fail"
    assert result.exit_state == "errored"
    assert result.findings[0].rule == "plugin-exception"
    assert result.findings[0].path == "src/app.py"
