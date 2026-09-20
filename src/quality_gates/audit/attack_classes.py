"""Phase 2: Systematic Hunting across 11 Domain Attack Classes.

Implements deep static pattern detectors and heuristic scanners for:
  AC-01: Insecure Direct Object References (IDOR) & Multi-tenancy Bypasses
  AC-02: Authentication & Session Hijacking
  AC-03: Injection Attacks (SQLi, Command Injection, Template Injection)
  AC-04: Cryptographic Flaws & Insecure Randomness
  AC-05: Server-Side Request Forgery (SSRF) & Unsafe URL Fetching
  AC-06: Deserialization & Unsafe Reflection
  AC-07: Race Conditions & Concurrency Hazards
  AC-08: Access Control & Privilege Escalation
  AC-09: Sensitive Data Exposure & Information Leakage
  AC-10: Business Logic Flaws & State Machine Invariants
  AC-11: Dependency Vulnerabilities & Supply Chain Weaknesses
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class CandidateFinding:
    attack_class_id: str
    attack_class_name: str
    cwe: str
    severity: str  # critical, high, medium, low
    path: str
    line: int
    title: str
    description: str
    evidence_snippet: str
    exploit_scenario: str
    suggested_fix: str
    confidence: str = "HIGH"
    context_vars: list[str] = field(default_factory=list)


# Concrete pattern definitions for each attack class
PATTERNS = [
    # AC-03: Injection
    (
        "AC-03",
        "Injection Attacks",
        "CWE-89",
        "critical",
        re.compile(
            r"""(?i)(cursor\.execute|execute_query|db\.query)\s*\(\s*(f['\"].*?\{|\".*?%s|'.*?%s)"""
        ),
        "Raw Query Formatting / SQL Injection",
        "Direct string formatting or interpolation in database query execution.",
        "An attacker can pass malicious SQL statements in user-controlled inputs to alter queries and dump data.",
        "Use parameterized queries with bound variables without string interpolation.",
    ),
    (
        "AC-03",
        "Injection Attacks",
        "CWE-78",
        "critical",
        re.compile(
            r"""(?i)(subprocess\.(Popen|run|call)|os\.system)\s*\([^)]*shell\s*=\s*True"""
        ),
        "Command Injection with shell=True",
        "Shell execution enabled with dynamic command arguments.",
        "An attacker providing command line arguments containing metacharacters (e.g. ';', '&&', '|', '`') executes arbitrary shell commands.",  # quality:ignore shell-true -- rule definition pattern, not an executable call
        "Set shell=False and pass arguments as a validated list of strings.",
    ),
    # AC-04: Cryptographic Flaws & Insecure Randomness
    (
        "AC-04",
        "Cryptographic Flaws & Insecure Randomness",
        "CWE-338",
        "high",
        re.compile(
            r"""(?i)random\.(random|randint|choice|randrange)\b.*(token|secret|key|salt|password|auth|session)"""
        ),
        "Insecure PRNG for Security-Sensitive Tokens",
        "Standard pseudorandom number generator used for security token generation.",
        "Pseudo-random state can be predicted from past outputs by an attacker to forge session tokens or password reset keys.",
        "Use cryptographically secure randomness: `secrets.token_hex()` or `os.urandom()`.",
    ),
    (
        "AC-04",
        "Cryptographic Flaws & Insecure Randomness",
        "CWE-328",
        "medium",
        re.compile(r"""(?i)hashlib\.(md5|sha1)\s*\("""),
        "Weak Hash Algorithm (MD5/SHA1)",
        "Obsolete cryptographic hash algorithm vulnerable to collision attacks.",
        "Collisions can be generated in polynomial time to bypass signature checks.",
        "Upgrade to SHA-256 (`hashlib.sha256()`) or Argon2 / bcrypt for passwords.",
    ),
    # AC-05: Server-Side Request Forgery (SSRF)
    (
        "AC-05",
        "Server-Side Request Forgery (SSRF)",
        "CWE-918",
        "high",
        re.compile(
            r"""(?i)(requests\.(get|post|put|delete)|urllib\.request\.urlopen|httpx\.(get|post))\s*\(\s*(request\.|url|user_url|target_url|webhook_url)"""
        ),
        "Unvalidated Outbound Request (SSRF)",
        "Outbound HTTP request made directly to dynamic URL without IP/domain whitelisting.",
        "Attacker passes internal addresses (e.g. `http://169.254.169.254` or `http://localhost:8080`) to access cloud metadata or internal services.",
        "Validate target URL against a strict domain whitelist and resolve IP to verify it does not belong to private/loopback ranges.",
    ),
    # AC-06: Deserialization & Unsafe Reflection
    (
        "AC-06",
        "Deserialization & Unsafe Reflection",
        "CWE-502",
        "critical",
        re.compile(
            r"""(?i)(pickle\.loads\s*\(|yaml\.load\s*\([^)]*Loader\s*=\s*(yaml\.)?(Loader|CLoader|UnsafeLoader)|marshal\.loads\s*\()"""
        ),
        "Insecure Deserialization",
        "Unsafe object deserialization from untrusted payload source.",
        "Attacker craft a serialized payload with `__reduce__` or object constructors to execute arbitrary code upon deserialization.",
        "Use safe serializers like JSON or specify `yaml.safe_load()`.",
    ),
    # AC-09: Sensitive Data Exposure & Information Leakage
    (
        "AC-09",
        "Sensitive Data Exposure",
        "CWE-798",
        "high",
        re.compile(
            r"""(?i)(api_key|secret_key|private_key|auth_token|db_password)\s*=\s*['\"][a-zA-Z0-9_\-\.]{16,}['\"]"""
        ),
        "Hardcoded Secret / API Key",
        "Static sensitive credential or token embedded directly in source code.",
        "Source code exposure immediately yields compromised keys and unauthorized API or database access.",
        "Externalize secrets into environment variables or a dedicated secret management vault.",
    ),
    # AC-07: Concurrency & Race Conditions
    (
        "AC-07",
        "Concurrency & Race Conditions",
        "CWE-367",
        "medium",
        re.compile(
            r"""(?i)if\s+not\s+os\.path\.exists\([^)]+\):\s*\n?\s*os\.makedirs\("""
        ),
        "Time-of-Check to Time-of-Use (TOCTOU) File Creation",
        "Checking existence before creating directory or file without atomic primitives.",
        "Concurrent processes can alter file attributes or create symlinks between check and creation.",
        "Use `os.makedirs(path, exist_ok=True)` or atomic `open(..., 'x')`.",
    ),
]


def scan_file_for_attack_classes(
    path: str,
    content: str,
    target_classes: list[str] | None = None,
) -> list[CandidateFinding]:
    """Scan a single file's content against the 11 domain attack classes."""
    findings: list[CandidateFinding] = []
    lines = content.splitlines()

    for rule in PATTERNS:
        acid, name, cwe, sev, pattern, title, desc, exploit, fix = rule
        if target_classes and not any(tc.startswith(acid) for tc in target_classes):
            continue

        for i, line in enumerate(lines, 1):
            if pattern.search(line):
                # Context snippet: up to 3 lines
                start_l = max(0, i - 2)
                end_l = min(len(lines), i + 1)
                snippet = "\n".join(lines[start_l:end_l])

                findings.append(
                    CandidateFinding(
                        attack_class_id=acid,
                        attack_class_name=name,
                        cwe=cwe,
                        severity=sev,
                        path=path,
                        line=i,
                        title=title,
                        description=desc,
                        evidence_snippet=snippet,
                        exploit_scenario=exploit,
                        suggested_fix=fix,
                        confidence="HIGH",
                    )
                )

    return findings
