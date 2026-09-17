"""Local triage dashboard for ``codesheriff serve``.

The API routes in :mod:`quality_gates.platform` answer machines; this module
answers humans.  It renders one self-contained page over the same
``.quality-reports/`` artifacts so a reviewer can see the verdict, triage
findings, inspect suppression drift, and watch run history without opening a
PR.  It stays offline: no CDN, no fonts, no telemetry.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--muted:#5d6673;--line:#e3e6ea;
--error:#c0392b;--warn:#b7791f;--ok:#1f7a45;--accent:#2563eb;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#171b23;--ink:#e7ebf1;
--muted:#98a1af;--line:#262c37;--chip:#222937;--accent:#7aa2f7}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{padding:1.4rem 1.5rem;border-bottom:1px solid var(--line);background:var(--card)}
h1{margin:0;font-size:1.3rem}
h2{font-size:1rem;margin:0 0 .7rem}
.sub{color:var(--muted);font-size:.85rem;margin:.25rem 0 0}
main{max-width:1000px;margin:0 auto;padding:1.2rem 1.2rem 3rem}
.cards{display:flex;flex-wrap:wrap;gap:.7rem;margin:0 0 1rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:.9rem 1.1rem;flex:1 1 150px}
.card .k{color:var(--muted);font-size:.75rem;text-transform:uppercase;
letter-spacing:.04em}
.card .v{font-size:1.6rem;font-weight:600}
.v.error{color:var(--error)}.v.warn{color:var(--warn)}.v.ok{color:var(--ok)}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:1rem 1.1rem;margin:1rem 0}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{text-align:left;padding:.45rem .5rem;border-bottom:1px solid var(--line);
vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:.78rem;text-transform:uppercase}
code{background:var(--chip);padding:.1rem .35rem;border-radius:5px;font-size:.85em}
.sev{font-weight:600}.sev.error{color:var(--error)}.sev.warning{color:var(--warn)}
form{display:flex;gap:.4rem;flex-wrap:wrap;margin:.5rem 0 0}
input,button{font:inherit;padding:.35rem .5rem;border-radius:7px;
border:1px solid var(--line);background:var(--bg);color:var(--ink)}
button{cursor:pointer;background:var(--accent);color:#fff;border-color:transparent}
.empty{color:var(--muted)}
"""

_SCRIPT = """
async function triage(action, fingerprint){
  const reason = (document.getElementById('reason')||{}).value || 'accepted false positive';
  const res = await fetch('/triage',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action,fingerprint,reason,days:90})});
  const out = await res.json();
  document.getElementById('triage-note').textContent = out.note || JSON.stringify(out);
  setTimeout(()=>location.reload(),600);
}
"""


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _findings(state: dict[str, Any]) -> list[dict[str, Any]]:
    payload = state.get("findings")
    rows = payload.get("findings", []) if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)]


def _gate_timings(state: dict[str, Any]) -> list[tuple[str, int]]:
    payload = state.get("metrics")
    rows = payload.get("results", []) if isinstance(payload, dict) else []
    timings = [
        (str(row.get("name") or "?"), int(row.get("duration_ms") or 0))
        for row in rows
        if isinstance(row, dict)
    ]
    return sorted(timings, key=lambda kv: -kv[1])


def render_dashboard(
    root: Path, state: dict[str, Any], audit: dict[str, Any] | None = None
) -> str:
    findings = _findings(state)
    errors = sum(1 for row in findings if row.get("severity") == "error")
    warnings = len(findings) - errors
    runs_payload = state.get("runs")
    runs = runs_payload if isinstance(runs_payload, list) else []
    verdict = "fail" if errors else ("warn" if warnings else "pass")
    audit = audit or {}
    cards = "".join(
        [
            _card("Verdict", verdict.upper(), verdict),
            _card("Errors", errors, "error" if errors else "ok"),
            _card("Warnings", warnings, "warn" if warnings else "ok"),
            _card("Suppressed", audit.get("active", 0), ""),
            _card("Orphaned waivers", audit.get("orphaned", 0), ""),
            _card("Runs", len(runs), ""),
        ]
    )
    return (
        "<!DOCTYPE html>\n<html lang='en'><head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'/>"
        "<title>Sheriff dashboard</title>"
        f"<style>{_CSS}</style></head><body>"
        "<header><h1>The Code Sheriff</h1>"
        f"<p class='sub'>{_esc(root)} · "
        f"{_esc((state.get('identity') or {}).get('app', 'codesheriff'))}</p></header>"
        f"<main><div class='cards'>{cards}</div>"
        f"{_findings_section(findings)}"
        f"{_runs_section(runs)}"
        f"{_audit_section(audit)}"
        f"{_timings_section(_gate_timings(state))}"
        "<p class='empty' id='triage-note'></p>"
        f"</main><script>{_SCRIPT}</script></body></html>\n"
    )


def _card(label: str, value: Any, tone: str) -> str:
    return (
        f"<div class='card'><div class='k'>{_esc(label)}</div>"
        f"<div class='v {tone}'>{_esc(value)}</div></div>"
    )


def _findings_section(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return (
            "<section><h2>Findings</h2>"
            "<p class='empty'>No findings in the last run.</p></section>"
        )
    rows = "".join(
        "<tr>"
        f"<td class='sev {_esc(row.get('severity'))}'>{_esc(row.get('severity'))}</td>"
        f"<td><code>{_esc(row.get('path'))}:{_esc(row.get('line'))}</code></td>"
        f"<td>{_esc(row.get('message'))}</td>"
        f"<td><code>{_esc(row.get('rule'))}</code></td>"
        f"<td><code>{_esc(row.get('fingerprint'))}</code></td>"
        f"<td><button onclick=\"triage('suppress','"
        f"{_esc(row.get('fingerprint'))}')\">suppress</button></td>"
        "</tr>"
        for row in findings[:100]
    )
    return (
        "<section><h2>Findings</h2>"
        "<form onsubmit='return false'>"
        "<input id='reason' placeholder='suppression reason'/>"
        "<span class='empty'>then click suppress on a row</span></form>"
        "<table><thead><tr><th>Severity</th><th>Where</th><th>Message</th>"
        "<th>Rule</th><th>Fingerprint</th><th></th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def _runs_section(runs: list[Any]) -> str:
    rows = "".join(
        "<tr>"
        f"<td><code>{_esc(row.get('run_id'))}</code></td>"
        f"<td class='sev {'error' if row.get('verdict') == 'fail' else 'ok'}'>"
        f"{_esc(row.get('verdict'))}</td>"
        f"<td>{_esc(row.get('when') or row.get('timestamp'))}</td>"
        f"<td>{_esc(row.get('errors'))}</td>"
        f"<td>{_esc(', '.join(row.get('gates') or []))}</td>"
        "</tr>"
        for row in runs[-12:]
        if isinstance(row, dict)
    )
    body = rows or "<tr><td colspan='5' class='empty'>no runs recorded</td></tr>"
    return (
        "<section><h2>Recent runs</h2>"
        "<table><thead><tr><th>Run</th><th>Verdict</th><th>When</th><th>Errors</th>"
        f"<th>Gates</th></tr></thead><tbody>{body}</tbody></table></section>"
    )


def _audit_section(audit: dict[str, Any]) -> str:
    items = audit.get("items") or []
    rows = "".join(
        "<tr>"
        f"<td><code>{_esc(row.get('fingerprint') or row.get('rule'))}</code></td>"
        f"<td>{_esc(row.get('state'))}</td>"
        f"<td>{'yes' if row.get('orphaned') else 'no'}</td>"
        f"<td>{'yes' if row.get('drifted') else 'no'}</td>"
        f"<td>{_esc(row.get('reason'))}</td>"
        f"<td>{_esc(row.get('owner'))}</td>"
        f"<td>{_esc(row.get('expires'))}</td>"
        "</tr>"
        for row in items
        if isinstance(row, dict)
    )
    body = rows or "<tr><td colspan='7' class='empty'>no waivers</td></tr>"
    summary = (
        f"{audit.get('active', 0)} active · {audit.get('expired', 0)} expired · "
        f"{audit.get('expiring', 0)} expiring · {audit.get('orphaned', 0)} orphaned · "
        f"{audit.get('drifted', 0)} held-through-drift"
    )
    return (
        f"<section><h2>Suppression audit</h2><p class='empty'>{summary}</p>"
        "<table><thead><tr><th>Scope</th><th>State</th><th>Orphaned</th>"
        "<th>Drifted</th><th>Reason</th><th>Owner</th><th>Expires</th></tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def _timings_section(timings: list[tuple[str, int]]) -> str:
    if not timings:
        return (
            "<section><h2>Gate timings</h2>"
            "<p class='empty'>no timing data (run with --timing)</p></section>"
        )
    rows = "".join(
        f"<tr><td>{_esc(name)}</td><td>{ms} ms</td></tr>" for name, ms in timings
    )
    return (
        "<section><h2>Gate timings</h2>"
        f"<table><thead><tr><th>Gate</th><th>Duration</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )


def triage(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Apply one triage action from the dashboard; returns a human note."""
    from quality_gates.ignore import (
        anchor_for,
        append_ignore,
        find_suppression_rule,
        remove_suppression,
    )

    action = str(payload.get("action") or "").lower()
    fingerprint = str(payload.get("fingerprint") or "")
    if not fingerprint:
        return {"ok": False, "note": "missing fingerprint"}
    if action == "unsuppress":
        removed = remove_suppression(root, fingerprint)
        return {
            "ok": removed,
            "note": f"removed {fingerprint}" if removed else "not found",
        }
    if action != "suppress":
        return {"ok": False, "note": f"unknown action {action}"}
    if find_suppression_rule(root, fingerprint) is not None:
        return {"ok": True, "note": f"already suppressed {fingerprint}"}
    from quality_gates.findings_artifact import load_last_findings

    row = next(
        (
            item
            for item in load_last_findings(root)
            if str(item.get("fingerprint") or "") == fingerprint
        ),
        {},
    )
    from quality_gates.models import Finding

    finding = Finding(
        gate=str(row.get("gate") or "review"),
        message=str(row.get("message") or ""),
        path=str(row.get("path") or "") or None,
        line=row.get("line") if isinstance(row.get("line"), int) else None,
        rule=str(row.get("rule") or "") or None,
        snippet=str(row.get("snippet") or "") or None,
    )
    days = payload.get("days")
    append_ignore(
        root,
        rule=str(row.get("rule") or "*"),
        path=str(row.get("path") or "") or None,
        gate=str(row.get("gate") or "") or None,
        reason=str(payload.get("reason") or "accepted false positive"),
        owner=str(payload.get("owner") or ""),
        days=None if days == 0 else int(days or 90),
        fingerprint=fingerprint,
        anchor=anchor_for(finding, root),
    )
    return {"ok": True, "note": f"suppressed {fingerprint}"}


def suppression_audit(root: Path, args: Any = None) -> dict[str, Any]:
    """Run the suppress command's audit in-process and return its JSON payload."""
    import io
    import types
    from contextlib import redirect_stdout

    from quality_gates.commands.suppress import handle

    ns = types.SimpleNamespace(
        command="suppress", action="audit", finding_id=None, json=True
    )
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        handle(ns, root, None)
    try:
        return json.loads(buffer.getvalue() or "{}")
    except json.JSONDecodeError:
        return {}


__all__ = ["render_dashboard", "suppression_audit", "triage"]
