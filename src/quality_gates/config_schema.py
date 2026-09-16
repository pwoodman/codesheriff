"""Configuration constants, tolerant coercers, and key allow-lists.

Split out of ``config.py`` so the dataclass/loader module stays readable; the
public names are re-exported from ``quality_gates.config``.
"""

from __future__ import annotations

from typing import Any

DEFAULT_REVIEW_SKIP_GLOBS = [
    "**/package-lock.json",
    "**/pnpm-lock.yaml",
    "**/yarn.lock",
    "**/npm-shrinkwrap.json",
    "**/Cargo.lock",
    "**/go.sum",
    "**/go.work.sum",
    "**/poetry.lock",
    "**/uv.lock",
    "**/composer.lock",
    "**/Gemfile.lock",
    "**/*.min.js",
    "**/*.min.css",
    "**/dist/**",
    "**/build/**",
    "**/vendor/**",
    "**/.venv/**",
    "**/generated/**",
    "**/*_generated.*",
    "**/*.pb.go",
    "**/*.pb.ts",
    "**/CHANGELOG.md",
    "**/changelog.md",
]

DEFAULT_EXCLUDE = [
    ".git",
    ".quality-gates",
    ".quality-reports",
    "node_modules",
    "dist",
    "build",
    "target",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    ".ruff_cache",
    ".pytest_cache",
    ".mypy_cache",
    "tests/fixtures",
    "tooling/js/node_modules",
    ".coverage",
    "htmlcov",
    ".zvec-grep",
    ".cursor",
    ".idea",
]


def _as_list(value: Any, fallback: list[str]) -> list[str]:
    if value is None:
        return list(fallback)
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return list(fallback)


def _as_dict(value: Any, fallback: dict[str, str]) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        return dict(fallback)
    return {str(key): str(val) for key, val in value.items()}


def _as_bool(value: Any, fallback: bool = False) -> bool:
    if value is None:
        return fallback
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_float(value: Any, fallback: float) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_ints(value: Any, fallback: list[int]) -> list[int]:
    if value is None:
        return list(fallback)
    if isinstance(value, list):
        out: list[int] = []
        for item in value:
            try:
                out.append(int(item))
            except (TypeError, ValueError):
                continue
        return out
    return list(fallback)


DEFAULT_FAIL_ON = [
    "format",
    "lint",
    "regex",
    "packages",
    "dry",
    "dead",
    "security",
    "compile",
    "contract",
    "impact",
    "test",
    "coverage",
    "audit",
    "ui",
    "version",
    "merge",
    "migration",
    "authorization",
    "resilience",
    "mutation",
    "performance",
    "plugins",
    "exceptions",
]
DEFAULT_GITHUB_GATES = [
    "format",
    "lint",
    "regex",
    "packages",
    "dead",
    "security",
    "impact",
    "audit",
    "version",
    "merge",
    "review",
    "comments",
]
POLICIES = ("observe", "adopt", "enforce")
TRUST_POLICIES = ("trusted", "prompt", "untrusted")
CONFIG_VERSION = 1
QUALITY_KEYS = frozenset(
    {
        "config_version",
        "languages",
        "fail_on",
        "ai_review",
        "auto_install",
        "trust",
        "offline",
        "execution_environment",
        "jobs",
        "cache",
        "required_tools",
        "ci",
        "compile",
        "contract",
        "coverage",
        "audit",
        "ui",
        "impact",
        "test",
        "version",
        "detect",
        "format",
        "lint",
        "regex",
        "packages",
        "dry",
        "dead",
        "sql",
        "review",
        "merge",
        "comments",
        "migration",
        "authorization",
        "resilience",
        "mutation",
        "performance",
        "plugins",
        "exceptions",
        "license",
        "policy",
        "baseline",
        "comment_on_pr",
        "retention",
        "cost",
        "outcomes",
        "notify",
        "packs",
        "rbac",
    }
)
