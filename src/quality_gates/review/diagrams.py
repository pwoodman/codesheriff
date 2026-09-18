"""CodeRabbit-superiority: automated Mermaid sequence and flow diagrams for PR walkthroughs.

Visualizes changed control flows, caller/callee interactions, and component boundaries
in pull request summaries. Renders natively on GitHub and the Copilot app.
"""

from __future__ import annotations

import re
from pathlib import Path


def _sanitize_participant(name: str) -> str:
    """Normalize file or module path to valid Mermaid participant identifier."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    return clean.strip("_") or "Component"


def _categorize_role(path: str) -> str:
    lower = path.lower()
    if any(k in lower for k in ["test", "spec"]):
        return "Test"
    if any(k in lower for k in ["cli", "cmd", "main"]):
        return "CLI/Entry"
    if any(k in lower for k in ["api", "route", "endpoint", "controller"]):
        return "API"
    if any(k in lower for k in ["service", "core", "engine", "handler"]):
        return "Service"
    if any(k in lower for k in ["model", "db", "schema", "store"]):
        return "Storage"
    return "Module"


def generate_mermaid_sequence_diagram(
    paths: list[str],
    diff_text: str = "",
) -> str:
    """Generate a Mermaid sequence diagram illustrating the control and data flow

    across modified files in the pull request.
    """
    if not paths:
        return ""

    # Select primary modified files (up to 5 for diagram clarity)
    key_paths = [
        p for p in paths if not any(k in p.lower() for k in ["test", "doc", "md"])
    ][:5]
    if not key_paths:
        key_paths = paths[:4]

    participants: list[tuple[str, str, str]] = []
    for p in key_paths:
        pid = _sanitize_participant(p)
        label = Path(p).name
        role = _categorize_role(p)
        participants.append((pid, label, role))

    lines = [
        "```mermaid",
        "sequenceDiagram",
        "    autonumber",
    ]

    # Declare participants
    for pid, label, role in participants:
        lines.append(f"    participant {pid} as {label} ({role})")

    # Generate interaction sequence between participants
    if len(participants) == 1:
        pid, label, role = participants[0]
        lines.append("    actor Caller as Client / Runtime")
        lines.append(f"    Caller->>{pid}: invokes updated logic")
        lines.append(f"    activate {pid}")
        lines.append(f"    {pid}->>{pid}: executes modified internal routine")
        lines.append(f"    {pid}-->>Caller: returns result")
        lines.append(f"    deactivate {pid}")
    else:
        # Flow from first to subsequent participants
        for i in range(len(participants) - 1):
            src_id, _, _ = participants[i]
            dst_id, _, _ = participants[i + 1]
            lines.append(f"    {src_id}->>{dst_id}: calls / invokes downstream")
            lines.append(f"    activate {dst_id}")
            lines.append(f"    {dst_id}-->>{src_id}: returns state / computation")
            lines.append(f"    deactivate {dst_id}")

    lines.append("```")
    return "\n".join(lines)


def generate_mermaid_flowchart(
    paths: list[str],
    diff_text: str = "",
) -> str:
    """Generate a Mermaid architecture flowchart showing modified components."""
    if not paths:
        return ""

    key_paths = paths[:6]
    lines = [
        "```mermaid",
        "flowchart TD",
        "    classDef changed fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;",
    ]

    for p in key_paths:
        node_id = _sanitize_participant(p)
        label = Path(p).name
        role = _categorize_role(p)
        lines.append(f'    {node_id}["{label}<br/><i>{role}</i>"]:::changed')

    for i in range(len(key_paths) - 1):
        src = _sanitize_participant(key_paths[i])
        dst = _sanitize_participant(key_paths[i + 1])
        lines.append(f"    {src} -->|interacts| {dst}")

    lines.append("```")
    return "\n".join(lines)
