"""Phase 1: Security Reconnaissance and Coverage Ledger.

Maps repository architecture, components, attack surfaces, and initializes
the coverage ledger tracking all files, entry points, and audited attack classes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import detect_languages, iter_project_files


@dataclass
class FileAuditEntry:
    path: str
    layer: str  # api, auth, model, service, util, config, test
    lines: int
    attack_surface: (
        str  # public_endpoint, internal_service, data_store, untrusted_input, low
    )
    status: str = "pending"  # pending, audited, skipped
    attack_classes_evaluated: list[str] = field(default_factory=list)


@dataclass
class CoverageLedger:
    total_files: int = 0
    total_lines: int = 0
    audited_files: int = 0
    audited_lines: int = 0
    files: dict[str, FileAuditEntry] = field(default_factory=dict)
    attack_classes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_files": self.total_files,
            "total_lines": self.total_lines,
            "audited_files": self.audited_files,
            "audited_lines": self.audited_lines,
            "coverage_pct": (
                round((self.audited_lines / self.total_lines) * 100, 2)
                if self.total_lines > 0
                else 0.0
            ),
            "attack_classes": self.attack_classes,
            "files": {p: asdict(entry) for p, entry in self.files.items()},
        }


def _classify_layer(rel_path: str) -> tuple[str, str]:
    """Determine layer and attack surface for a file path."""
    lower = rel_path.lower()
    if any(t in lower for t in ["test", "spec", "__tests__"]):
        return "test", "low"
    if any(a in lower for a in ["auth", "token", "session", "jwt", "crypto", "oauth"]):
        return "auth", "untrusted_input"
    if any(
        api in lower for api in ["api", "route", "endpoint", "controller", "handler"]
    ):
        return "api", "public_endpoint"
    if any(
        m in lower for m in ["model", "schema", "entity", "db", "repository", "query"]
    ):
        return "model", "data_store"
    if any(s in lower for s in ["service", "client", "worker", "agent", "job"]):
        return "service", "internal_service"
    if any(c in lower for c in ["config", "settings", ".env", "yaml", "toml", "json"]):
        return "config", "low"
    return "util", "low"


def build_coverage_ledger(
    root: Path,
    config: QualityConfig | None = None,
    attack_classes: list[str] | None = None,
) -> CoverageLedger:
    """Build initial coverage ledger mapping all repository files and attack surfaces."""
    cfg = config or QualityConfig()
    classes = attack_classes or [
        "AC-01:IDOR",
        "AC-02:Auth/Session",
        "AC-03:Injection",
        "AC-04:Crypto/PRNG",
        "AC-05:SSRF",
        "AC-06:Deserialization",
        "AC-07:Concurrency/TOCTOU",
        "AC-08:AccessControl",
        "AC-09:DataExposure",
        "AC-10:BusinessLogic",
        "AC-11:SupplyChain",
    ]

    ledger = CoverageLedger(attack_classes=classes)
    for p in iter_project_files(root, cfg):
        rel = p.relative_to(root).as_posix()
        try:
            line_count = len(
                p.read_text(encoding="utf-8", errors="ignore").splitlines()
            )
        except OSError:
            line_count = 0

        layer, surface = _classify_layer(rel)
        ledger.files[rel] = FileAuditEntry(
            path=rel,
            layer=layer,
            lines=line_count,
            attack_surface=surface,
            status="pending",
            attack_classes_evaluated=[],
        )
        ledger.total_files += 1
        ledger.total_lines += line_count

    return ledger


def generate_architecture_map(
    root: Path,
    ledger: CoverageLedger,
    config: QualityConfig | None = None,
) -> str:
    """Generate architecture.md mapping system components, entry points, and trust boundaries."""
    cfg = config or QualityConfig()
    languages = detect_languages(root, cfg)

    layer_counts: dict[str, int] = {}
    surface_counts: dict[str, int] = {}
    for entry in ledger.files.values():
        layer_counts[entry.layer] = layer_counts.get(entry.layer, 0) + 1
        surface_counts[entry.attack_surface] = (
            surface_counts.get(entry.attack_surface, 0) + 1
        )

    lines = [
        "# System Architecture & Trust Boundary Map",
        "",
        "## 1. Executive Reconnaissance Summary",
        f"- **Repository Root**: `{root.name}`",
        f"- **Primary Languages**: {', '.join(languages) if languages else 'Not detected'}",
        f"- **Total Audited Scope**: {ledger.total_files} files ({ledger.total_lines:,} lines of code)",
        "",
        "## 2. Attack Surface Breakdown",
        "| Attack Surface | File Count | Risk Level | Description |",
        "|---|---|---|---|",
        f"| Public Endpoints / Handlers | {surface_counts.get('public_endpoint', 0)} | High | Direct unauthenticated or externally exposed ingestion points |",
        f"| Authentication & Tokens | {surface_counts.get('untrusted_input', 0)} | Critical | Credential, session, signature, and cryptographic boundaries |",
        f"| Data Stores & ORM Models | {surface_counts.get('data_store', 0)} | High | Persistent storage, query generation, and object deserialization |",
        f"| Internal Services & Workers | {surface_counts.get('internal_service', 0)} | Medium | Business logic pipelines and internal RPCs |",
        f"| Utilities & Config | {surface_counts.get('low', 0)} | Low | Shared helper libraries and static assets |",
        "",
        "## 3. Layer Distribution",
    ]
    for layer, count in sorted(layer_counts.items(), key=lambda x: -x[1]):
        lines.append(f"- **{layer.capitalize()}**: {count} file(s)")

    lines.extend(
        [
            "",
            "## 4. Trust Boundaries & Assumptions",
            "1. **Client -> API Boundary**: External user inputs must be strictly validated and sanitized before consumption.",
            "2. **API -> Service Boundary**: Caller privileges and tenant contexts must be propagated and re-verified at every invocation.",
            "3. **Service -> Persistence Boundary**: Parameterized queries and ORM abstractions must prevent command and query injection.",
            "4. **Outbound Network Boundary**: All egress requests (URLs, webhooks) must be bounded by SSRF IP blacklists and scheme whitelists.",
            "",
        ]
    )
    return "\n".join(lines)


def write_recon_artifacts(out_dir: Path, ledger: CoverageLedger, arch_md: str) -> None:
    """Save architecture.md and coverage-ledger.json to output directory."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "architecture.md").write_text(arch_md, encoding="utf-8")
    (out_dir / "coverage-ledger.json").write_text(
        json.dumps(ledger.to_dict(), indent=2), encoding="utf-8"
    )
