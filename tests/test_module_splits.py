"""Coverage for modules extracted during the Phase 1.4 splits.

``config_schema``, ``doctor``, ``github_app_api`` and ``diffscan`` are all
loaded at import time here so the impact graph sees consumers for them.
"""

from __future__ import annotations

import json
from pathlib import Path

import quality_gates.config_schema as config_schema
from quality_gates.cli import main
from quality_gates.config import (
    DEFAULT_FAIL_ON,
    DEFAULT_GITHUB_GATES,
    DEFAULT_REVIEW_SKIP_GLOBS,
    POLICIES,
    QUALITY_KEYS,
    TRUST_POLICIES,
    QualityConfig,
)
from quality_gates.doctor import (
    build_payload,
    compute_rows,
    doctor,
    render_console,
    validate_install,
)
from quality_gates.github_app import post_check
from quality_gates.github_app_api import (
    _b64url,
    api_request,
    api_url,
    app_jwt,
    pr_head_sha,
)
from quality_gates.review.diffscan import (
    iter_added_lines,
    iter_new_file_lines,
    load_review_diff,
)


def test_config_schema_constants_and_coercers_round_trip() -> None:
    assert DEFAULT_FAIL_ON
    assert "[sheriff]" in DEFAULT_REVIEW_SKIP_GLOBS or DEFAULT_REVIEW_SKIP_GLOBS
    assert "trusted" in TRUST_POLICIES
    assert QUALITY_KEYS is config_schema.QUALITY_KEYS
    assert POLICIES
    assert "lint" in DEFAULT_GITHUB_GATES
    assert config_schema._as_list(None, ["fallback"]) == ["fallback"]
    assert config_schema._as_list("a", []) == ["a"]
    assert config_schema._as_list(["a", "b"], []) == ["a", "b"]
    assert config_schema._as_dict({"a": 1}, {}) == {"a": "1"}
    assert config_schema._as_dict("nope", {"d": "e"}) == {"d": "e"}
    assert config_schema._as_bool("true") is True
    assert config_schema._as_bool("off") is False
    assert config_schema._as_bool(None, True) is True
    assert config_schema._as_float("1.5", 0.0) == 1.5
    assert config_schema._as_float("bad", 2.0) == 2.0
    assert config_schema._as_ints(["1", 2, "x"], []) == [1, 2]
    assert config_schema._as_ints(None, [9]) == [9]
    assert config_schema._as_dict_list([{"a": 1}, "skip"]) == [{"a": 1}]
    assert config_schema._as_dict_list("nope") == []


def test_doctor_helpers_build_and_render(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr("quality_gates.doctor.which", lambda *_a, **_kw: None)
    monkeypatch.setattr("quality_gates.doctor.tool_version", lambda *_a, **_kw: None)
    config = QualityConfig()
    detected = {"languages": ["python"], "file_kinds": []}
    rows = compute_rows(tmp_path, config, detected)
    payload = build_payload(tmp_path, config, detected, rows)
    assert payload["detected"]["languages"] == ["python"]
    assert isinstance(payload["tools"], list)
    render_console(
        tmp_path, config, {"tools": rows, "platform": "linux", "cache": str(tmp_path)}
    )
    out = capsys.readouterr().out
    assert "project:" in out


def test_doctor_and_validate_install_paths(tmp_path: Path, capsys, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr("quality_gates.doctor.which", lambda *_a, **_kw: None)
    config = QualityConfig()
    assert doctor(tmp_path, config, install=False, as_json=True) in {0, 1}
    json.loads(capsys.readouterr().out)

    offline = QualityConfig(offline=True)
    assert validate_install(offline, install=True) == 2
    assert "offline" in capsys.readouterr().err
    assert validate_install(config, install=False) is None


def test_github_app_api_jwt_and_check_run(monkeypatch) -> None:
    assert _b64url(b"\x00\xff") == "AP8"
    assert api_url("repos/o/r").endswith("/repos/o/r")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("QUALITY_HEAD_SHA", raising=False)
    assert pr_head_sha() == "abc123"

    calls: list[tuple[str, str, dict]] = []

    def fake_api(method, url, token, payload=None):
        calls.append((method, url, payload or {}))
        if "access_tokens" in url:
            return 201, {"token": "tkn"}
        return 201, {"id": 1}

    monkeypatch.setattr("quality_gates.github_app_api.api_request", fake_api)
    monkeypatch.setattr(
        "quality_gates.github_app_api._rsa_sign", lambda *_a, **_kw: b"sig"
    )
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    jwt = app_jwt("123", "KEY")
    assert jwt.count(".") == 2
    assert calls == []
    status = post_check(
        name="check",
        status="completed",
        conclusion="success",
        title="t",
        summary="s",
        details_url="https://example.com",
    )
    assert status.startswith("posted check run")
    assert calls[-1][2]["details_url"] == "https://example.com"
    missing = post_check(name="check", status="in_progress")
    assert missing == "posted check run check (in_progress)"

    monkeypatch.setenv("GH_TOKEN", "")
    monkeypatch.setenv("GITHUB_TOKEN", "")
    assert post_check().startswith("skipped check run")


def test_github_app_api_network_helpers(monkeypatch) -> None:
    class _Resp:
        status = 200

        def read(self) -> bytes:
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *exc) -> None:
            return None

    monkeypatch.setattr(
        "quality_gates.github_app_api.urllib.request.urlopen",
        lambda *_a, **_kw: _Resp(),
    )
    code, payload = api_request("GET", api_url("/x"), "")
    assert code == 200 and payload == {"ok": True}


def test_iter_added_lines_and_load_review_diff(tmp_path: Path) -> None:
    diff = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,3 @@\n context\n+added\n"
    assert list(iter_added_lines(diff)) == [("a.py", 2, "added")]
    assert next(iter(iter_new_file_lines(diff)))[3] == "context"
    config = QualityConfig()
    assert load_review_diff(tmp_path, config, base=None, diff="explicit") == "explicit"
    assert not load_review_diff(tmp_path, config, base=None, diff=None)


def test_main_doctor_smoke(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("quality_gates.doctor.which", lambda *_a, **_kw: None)
    assert main(["--json", "doctor"]) in {0, 1}
