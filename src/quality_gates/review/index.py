"""On-disk symbol / route / schema index for cross-file review context.

Persistent graph that survives across runs, with incremental updates.
Supports NL Q&A queries and one-click agent handoff context.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files

_DEF = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|function|class|interface|fn|func)\s+"
    r"([A-Za-z_][\w]*)",
    re.M,
)
_ROUTE = re.compile(
    r"""(?:@(?:app|router)\.(?:get|post|put|patch|delete)|
        (?:app|router)\.(?:get|post|put|patch|delete)\()""",
    re.I | re.X,
)
_SCHEMA = re.compile(r"(?:message|type|interface|model|table)\s+([A-Za-z_]\w*)", re.I)

INDEX_NAME = "symbol-index.json"
GRAPH_DIR = ".quality-graph"
GRAPH_VERSION = "2.0.0"


def build_symbol_index(root: Path, config: QualityConfig) -> dict[str, Any]:
    """Build or incrementally update the symbol index."""
    graph_dir = root / GRAPH_DIR
    graph_dir.mkdir(parents=True, exist_ok=True)
    existing = _load_graph(graph_dir)
    existing_hashes = {
        s.get("path"): s.get("_hash")
        for s in existing.get("symbols", [])
        if s.get("path")
    }

    symbols: list[dict[str, Any]] = existing.get("symbols", [])
    updated_paths: set[str] = set()
    deleted_paths = set(existing_hashes.keys())

    for path in iter_project_files(root, config):
        rel = path.relative_to(root).as_posix()
        deleted_paths.discard(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if len(text) > 400_000:
            continue

        content_hash = hashlib.md5(text.encode()).hexdigest()
        if existing_hashes.get(rel) == content_hash and rel in {
            s.get("path") for s in symbols
        }:
            continue

        symbols = [s for s in symbols if s.get("path") != rel]
        updated_paths.add(rel)

        for match in _DEF.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            symbols.append(
                {
                    "kind": "symbol",
                    "name": match.group(1),
                    "path": rel,
                    "line": line,
                    "_hash": content_hash,
                }
            )
        if _ROUTE.search(text):
            symbols.append(
                {
                    "kind": "route",
                    "name": rel,
                    "path": rel,
                    "line": 1,
                    "_hash": content_hash,
                }
            )
        for match in _SCHEMA.finditer(text):
            if path.suffix in {".proto", ".graphql", ".sql", ".prisma"}:
                symbols.append(
                    {
                        "kind": "schema",
                        "name": match.group(1),
                        "path": rel,
                        "line": text.count("\n", 0, match.start()) + 1,
                        "_hash": content_hash,
                    }
                )

    for path in deleted_paths:
        symbols = [s for s in symbols if s.get("path") != path]

    payload = {
        "schema_version": GRAPH_VERSION,
        "symbols": symbols,
        "count": len(symbols),
        "updated_paths": list(updated_paths),
        "deleted_paths": list(deleted_paths),
    }
    _save_graph(graph_dir, payload)

    reports = root / ".quality-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / INDEX_NAME).write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _load_graph(graph_dir: Path) -> dict[str, Any]:
    path = graph_dir / INDEX_NAME
    if not path.is_file():
        return {"symbols": [], "count": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"symbols": [], "count": 0}
    return data if isinstance(data, dict) else {"symbols": [], "count": 0}


def _save_graph(graph_dir: Path, payload: dict[str, Any]) -> None:
    path = graph_dir / INDEX_NAME
    clean = {k: v for k, v in payload.items() if not k.startswith("_")}
    path.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")


def load_symbol_index(root: Path) -> dict[str, Any]:
    path = root / ".quality-reports" / INDEX_NAME
    if not path.is_file():
        graph_path = root / GRAPH_DIR / INDEX_NAME
        if graph_path.is_file():
            path = graph_path
        else:
            return {"symbols": [], "count": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"symbols": [], "count": 0}
    return data if isinstance(data, dict) else {"symbols": [], "count": 0}


def search_symbols(
    index: dict[str, Any], query: str, *, limit: int = 8
) -> list[dict[str, Any]]:
    needle = query.lower().strip()
    if not needle:
        return []
    hits = []
    for item in index.get("symbols") or []:
        name = str(item.get("name") or "").lower()
        path = str(item.get("path") or "").lower()
        if needle in name or needle in path:
            hits.append(item)
        if len(hits) >= limit:
            break
    return hits


def callers_of(index: dict[str, Any], name: str) -> list[str]:
    hits = search_symbols(index, name, limit=12)
    return [f"{item.get('path')}:{item.get('line')}" for item in hits]


def answer_question(root: Path, question: str) -> dict[str, Any]:
    """Natural language Q&A over the codebase graph.

    Returns a structured answer with relevant symbols, files, and context
    for one-click agent handoff.
    """
    index = load_symbol_index(root)
    question_lower = question.lower().strip()

    keywords = [w for w in re.split(r"\W+", question_lower) if len(w) > 2]

    relevant_symbols: list[dict[str, Any]] = []
    for keyword in keywords:
        hits = search_symbols(index, keyword, limit=10)
        relevant_symbols.extend(hits)

    seen = set()
    unique_symbols = []
    for s in relevant_symbols:
        key = (s.get("name"), s.get("path"))
        if key not in seen:
            seen.add(key)
            unique_symbols.append(s)

    files = sorted({s.get("path", "") for s in unique_symbols if s.get("path")})

    context_parts = []
    for s in unique_symbols[:15]:
        kind = s.get("kind", "symbol")
        name = s.get("name", "?")
        path = s.get("path", "?")
        line = s.get("line", "?")
        context_parts.append(f"{kind} `{name}` at {path}:{line}")

    return {
        "question": question,
        "symbols_found": len(unique_symbols),
        "files": files[:20],
        "context": context_parts[:15],
        "agent_prompt": (
            f"Codebase context for: {question}\n\n"
            f"Relevant symbols:\n"
            + "\n".join(context_parts[:10])
            + f"\n\nFiles involved: {', '.join(files[:10])}"
        ),
    }


def get_agent_handoff_context(
    root: Path,
    *,
    finding_path: str | None = None,
    finding_rule: str | None = None,
) -> dict[str, Any]:
    """Generate one-click agent handoff context for a finding.

    Returns context that can be passed directly to Claude Code, Cursor, or Codex.
    """
    index = load_symbol_index(root)
    context: dict[str, Any] = {
        "tool": "codesheriff",
        "finding_path": finding_path,
        "finding_rule": finding_rule,
        "related_symbols": [],
        "related_files": [],
        "prompt": "",
    }

    if finding_path:
        related = [s for s in index.get("symbols", []) if s.get("path") == finding_path]
        context["related_symbols"] = related[:20]

        call_pattern = re.compile(r"\b([A-Za-z_]\w*)\s*\(", re.M)
        try:
            full_path = root / finding_path
            if full_path.is_file():
                text = full_path.read_text(encoding="utf-8")
                calls = set(call_pattern.findall(text))
                for call_name in calls:
                    callers = callers_of(index, call_name)
                    for caller in callers:
                        caller_path = caller.split(":")[0]
                        if caller_path != finding_path:
                            context["related_files"].append(caller_path)
        except (OSError, UnicodeDecodeError):
            pass

    context["related_files"] = sorted(set(context["related_files"]))[:10]

    parts = [f"Fix the {finding_rule or 'issue'} in {finding_path or 'the codebase'}."]
    if context["related_symbols"]:
        parts.append("\nRelated symbols:")
        for s in context["related_symbols"][:5]:
            parts.append(f"  - {s.get('name')} at {s.get('path')}:{s.get('line')}")
    if context["related_files"]:
        parts.append(
            f"\nCheck these related files: {', '.join(context['related_files'][:5])}"
        )
    parts.append("\nRun `codesheriff oracle --prompt` after fixing to verify.")
    context["prompt"] = "\n".join(parts)

    return context
