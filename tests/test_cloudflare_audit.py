"""Tests for Cloudflare Security Audit Skill superiority harness."""

from pathlib import Path

from quality_gates.audit.attack_classes import (
    CandidateFinding,
    scan_file_for_attack_classes,
)
from quality_gates.audit.recon import (
    build_coverage_ledger,
    generate_architecture_map,
)
from quality_gates.audit.security_audit import run_security_audit
from quality_gates.audit.verifier import evaluate_adversarial_disprover


def test_recon_and_coverage_ledger(tmp_path: Path):
    (tmp_path / "api.py").write_text("def handle_request(): pass\n", encoding="utf-8")
    (tmp_path / "auth.py").write_text("def verify_jwt(): pass\n", encoding="utf-8")
    (tmp_path / "test_api.py").write_text("def test(): pass\n", encoding="utf-8")

    ledger = build_coverage_ledger(tmp_path)
    assert ledger.total_files == 3
    assert "api.py" in ledger.files
    assert ledger.files["api.py"].layer == "api"
    assert ledger.files["auth.py"].layer == "auth"
    assert ledger.files["test_api.py"].layer == "test"

    arch_md = generate_architecture_map(tmp_path, ledger)
    assert "# System Architecture & Trust Boundary Map" in arch_md
    assert "Attack Surface Breakdown" in arch_md


def test_attack_classes_hunting():
    vulnerable_code = """
import os
import subprocess

def bad_sql(user_input):
    cursor.execute(f"SELECT * FROM users WHERE id = {user_input}")

def bad_shell(cmd):
    subprocess.Popen(cmd, shell=True)

def safe_yaml(data):
    yaml.safe_load(data)
"""
    findings = scan_file_for_attack_classes("app.py", vulnerable_code)
    attack_classes = {f.attack_class_id for f in findings}
    assert "AC-03" in attack_classes
    assert any("SQL Injection" in f.title for f in findings)
    assert any("shell=True" in f.title for f in findings)


def test_adversarial_disprover_and_grounding(tmp_path: Path):
    vuln_file = tmp_path / "vuln.py"
    vuln_file.write_text(
        "import subprocess\nsubprocess.Popen(cmd, shell=True)\n",
        encoding="utf-8",
    )

    # Valid candidate on existing line
    candidate = CandidateFinding(
        attack_class_id="AC-03",
        attack_class_name="Injection Attacks",
        cwe="CWE-78",
        severity="critical",
        path="vuln.py",
        line=2,
        title="Command Injection",
        description="Shell execution enabled.",
        evidence_snippet="subprocess.Popen(cmd, shell=True)",
        exploit_scenario="Arbitrary shell execution.",
        suggested_fix="Set shell=False.",
    )

    verified = evaluate_adversarial_disprover(candidate, tmp_path)
    assert verified.verdict == "CONFIRMED"
    assert verified.grounded is True

    # Grounding failure: file does not exist
    fake_candidate = CandidateFinding(
        attack_class_id="AC-03",
        attack_class_name="Injection Attacks",
        cwe="CWE-78",
        severity="critical",
        path="nonexistent.py",
        line=10,
        title="Fake",
        description="Fake",
        evidence_snippet="fake",
        exploit_scenario="fake",
        suggested_fix="fake",
    )
    unverified = evaluate_adversarial_disprover(fake_candidate, tmp_path)
    assert unverified.verdict == "REJECTED"
    assert unverified.grounded is False

    # Disprover: sanitized code
    safe_file = tmp_path / "safe.py"
    safe_file.write_text(
        "import shlex\nimport subprocess\nclean = shlex.quote(cmd)\nsubprocess.Popen(clean, shell=True)\n",
        encoding="utf-8",
    )
    safe_candidate = CandidateFinding(
        attack_class_id="AC-03",
        attack_class_name="Injection Attacks",
        cwe="CWE-78",
        severity="critical",
        path="safe.py",
        line=4,
        title="Command Injection",
        description="Shell execution.",
        evidence_snippet="subprocess.Popen(clean, shell=True)",
        exploit_scenario="Exploit",
        suggested_fix="Fix",
    )
    disproven = evaluate_adversarial_disprover(safe_candidate, tmp_path)
    assert disproven.verdict == "REJECTED"
    assert "sanitized" in disproven.disproof_reason.lower()


def test_comprehensive_reporting(tmp_path: Path):
    file_p = tmp_path / "app.py"
    file_p.write_text("import pickle\npickle.loads(data)\n", encoding="utf-8")

    out_dir = tmp_path / "audit_output"
    res = run_security_audit(tmp_path, out_dir=out_dir)

    assert res.candidates_count >= 1
    assert any(vf.verdict == "CONFIRMED" for vf in res.confirmed_findings)
    assert (out_dir / "REPORT.md").exists()
    assert (out_dir / "FINDINGS-DETAIL.md").exists()
    assert (out_dir / "NEEDS-VALIDATION.md").exists()
    assert (out_dir / "architecture.md").exists()
    assert (out_dir / "coverage-ledger.json").exists()

    report_text = (out_dir / "REPORT.md").read_text(encoding="utf-8")
    assert "Security Audit & Vulnerability Assessment Report" in report_text
    assert "Domain Attack Class Coverage" in report_text
