"""``codesheriff ask`` — natural-language semantic repo Q&A over the local symbol knowledge graph.

Outperforms Greptile by running locally in milliseconds without code egress or
external cloud indexing subscriptions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from quality_gates.config import QualityConfig
from quality_gates.review.index import (
    build_symbol_index,
    load_symbol_index,
    search_symbols,
)


def query_repo(
    root: Path,
    config: QualityConfig,
    query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Execute local semantic repository query using symbol and route knowledge graph."""
    index = load_symbol_index(root)
    if not index.get("symbols"):
        index = build_symbol_index(root, config)

    results = search_symbols(index, query, limit=limit)
    return {
        "query": query,
        "count": len(results),
        "results": results,
    }


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "ask",
        help="query repository architecture and symbols locally (outperforming Greptile with 0 cloud egress)",
    )
    parser.add_argument(
        "query", help="natural-language or symbol query to find in the repository"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="maximum number of matching symbols/routes to return (default: 10)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="output results in structured JSON format",
    )


def handle(args: argparse.Namespace, root: Path, config: QualityConfig) -> int | None:
    if getattr(args, "command", None) != "ask":
        return None

    res = query_repo(root, config, args.query, limit=args.limit)

    if args.json:
        print(json.dumps(res, indent=2))
        return 0

    print(
        f"Code Sheriff Repository Knowledge: Found {res['count']} match(es) for '{args.query}'\n"
    )
    if not res["results"]:
        print("No matching symbols, routes, or schema definitions found.")
        return 0

    for idx, item in enumerate(res["results"], start=1):
        kind = item.get("kind", "symbol").upper()
        name = item.get("name", "")
        path = item.get("path", "")
        line = item.get("line", 1)
        print(f"{idx}. [{kind}] {name} -> {path}:{line}")

    return 0


__all__ = ["handle", "query_repo", "register"]
