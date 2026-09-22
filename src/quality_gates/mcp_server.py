"""Minimal MCP stdio server so coding agents can loop until gates are green."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

from quality_gates import __version__
from quality_gates.oracle import (
    finding_from_reports,
    remaining_from_reports,
    render_prompt,
)

TOOLS = [
    {
        "name": "codesheriff_oracle",
        "description": (
            "Read the last CodeSheriff run and return remaining blocking "
            "findings, a fix playbook (next action first), and a merge "
            "certificate. Iterate until green is true and certificate.ready."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "boolean",
                    "description": "If true, return a fix-it prompt instead of JSON.",
                }
            },
        },
    },
    {
        "name": "codesheriff_run",
        "description": (
            "Run CodeSheriff (same as `codesheriff run`). Optional only/skip lists. "
            "Returns remaining blockers after the run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "only": {"type": "string"},
                "skip": {"type": "string"},
                "full": {"type": "boolean"},
            },
        },
    },
    {
        "name": "codesheriff_review",
        "description": "Run the AI/heuristic review gate against the review base.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base": {"type": "string"},
                "post": {"type": "boolean"},
            },
        },
    },
    {
        "name": "codesheriff_finding_context",
        "description": (
            "Pack one finding (what/where/why/fix/patch/verify) for a coding agent. "
            "Pass id to select; otherwise the first blocker."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
        },
    },
    {
        "name": "codesheriff_apply_fix",
        "description": (
            "Apply a finding's patch to the working tree. Pass finding id from "
            "codesheriff_finding_context. Re-run codesheriff_oracle after."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
        },
    },
    {
        "name": "codesheriff_merge",
        "description": (
            "Dry-merge HEAD into the base branch with git merge-tree. Reports "
            "textual conflicts and optionally compile/impact on the merged tree. "
            "Set siblings to also check other open PR heads."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "base": {"type": "string"},
                "verify": {"type": "boolean"},
                "siblings": {"type": "boolean"},
            },
        },
    },
    {
        "name": "codesheriff_fix",
        "description": (
            "Apply safe automatic remediations: format --write, ruff --fix, "
            "and finding patches. Then re-run codesheriff_oracle."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "patches": {
                    "type": "boolean",
                    "description": "Also apply finding patches (default true).",
                }
            },
        },
    },
    {
        "name": "codesheriff_certify",
        "description": (
            "Read or refresh the merge certificate. ready/auto_merge=ready "
            "means the change can be auto-merged if The Code Sheriff is required."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "codesheriff_pr_comments",
        "description": (
            "List unresolved GitHub review threads on the current pull request "
            "(Greptile, BugBot, humans, Sheriff). Apply suggestion patches with "
            "codesheriff_apply_fix, then re-run codesheriff_oracle."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "fail": {
                    "type": "boolean",
                    "description": "If true, treat unresolved threads as blocking.",
                }
            },
        },
    },
    {
        "name": "codesheriff_status",
        "description": (
            "Return the project health status: gate verdicts, blockers, "
            "certificate state, and agent loop status. Use --prompt for a "
            "human-readable summary."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "boolean"},
                "verbose": {"type": "boolean"},
            },
        },
    },
    {
        "name": "codesheriff_hooks",
        "description": (
            "Manage git hooks and automations. List installed hooks, "
            "install/uninstall pre-commit hooks, and show automation triggers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "list", "install", "uninstall"],
                    "description": "Action to perform on hooks.",
                }
            },
        },
    },
    {
        "name": "codesheriff_agent",
        "description": (
            "Unified agent interface: get context, next action, findings, "
            "prompt, or explanation. Use action='loop' for the full agent loop."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "context",
                        "findings",
                        "next",
                        "apply",
                        "prompt",
                        "loop",
                        "explain",
                    ],
                    "description": "Agent action to perform.",
                },
                "id": {
                    "type": "string",
                    "description": "Finding ID for apply/context/explain.",
                },
                "full": {
                    "type": "boolean",
                    "description": "Include full context details.",
                },
            },
        },
    },
    {
        "name": "codesheriff_interact",
        "description": (
            "Interactive slash-command mode. Parse /sheriff commands, "
            "list available commands, or enter interactive mode."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Slash command like /sheriff review.",
                },
                "reply": {
                    "type": "string",
                    "description": "Reply text for slash commands.",
                },
            },
        },
    },
    {
        "name": "codesheriff_ask",
        "description": (
            "Natural language Q&A over the codebase. Ask questions like "
            "'where is auth handled?' or 'what calls this function?' to get "
            "symbol context and related files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Natural language question about the codebase.",
                }
            },
            "required": ["question"],
        },
    },
    {
        "name": "codesheriff_handoff",
        "description": (
            "Generate one-click agent handoff context for a finding. "
            "Returns a prompt ready for Claude Code, Cursor, or Codex."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Finding ID from codesheriff_finding_context.",
                },
                "path": {
                    "type": "string",
                    "description": "File path to get context for.",
                },
                "rule": {
                    "type": "string",
                    "description": "Rule name for context.",
                },
            },
        },
    },
]


def serve(
    stdin=None,
    stdout=None,
    *,
    runner: Callable[[list[str]], int] | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    run = runner or _default_runner
    while True:
        message = _read(stdin)
        if message is None:
            return 0
        response = handle(message, runner=run)
        if response is not None:
            _write(stdout, response)
        if message.get("method") == "exit":
            return 0


def handle(
    message: dict[str, Any], *, runner: Callable[[list[str]], int]
) -> dict[str, Any] | None:
    method = message.get("method")
    msg_id = message.get("id")
    if method == "initialize":
        return _ok(
            msg_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "codesheriff", "version": __version__},
            },
        )
    if method == "notifications/initialized" or method == "exit":
        return None
    if method == "ping":
        return _ok(msg_id, {})
    if method == "tools/list":
        return _ok(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        try:
            text = _call_tool(str(name), args, runner)
        except Exception as exc:
            return _ok(
                msg_id,
                {
                    "content": [{"type": "text", "text": f"tool error: {exc}"}],
                    "isError": True,
                },
            )
        return _ok(msg_id, {"content": [{"type": "text", "text": text}]})
    if msg_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Unknown method {method}"},
    }


def _call_tool(
    name: str, args: dict[str, Any], runner: Callable[[list[str]], int]
) -> str:
    name = name.replace("quality_", "codesheriff_", 1)
    if name == "codesheriff_oracle":
        payload = remaining_from_reports(_root())
        if args.get("prompt"):
            return render_prompt(payload)
        return json.dumps(payload, indent=2)
    if name == "codesheriff_run":
        argv = ["run"]
        if args.get("only"):
            argv.extend(["--only", str(args["only"])])
        if args.get("skip"):
            argv.extend(["--skip", str(args["skip"])])
        if args.get("full"):
            argv.append("--full")
        code = runner(argv)
        payload = remaining_from_reports(_root())
        payload["exit_code"] = code
        return json.dumps(payload, indent=2)
    if name == "codesheriff_review":
        argv = ["review"]
        if args.get("base"):
            argv.extend(["--base", str(args["base"])])
        if args.get("post"):
            argv.append("--post")
        code = runner(argv)
        payload = remaining_from_reports(_root())
        payload["exit_code"] = code
        return json.dumps(payload, indent=2)
    if name == "codesheriff_finding_context":
        finding_id = str(args["id"]) if args.get("id") else None
        return json.dumps(finding_from_reports(_root(), finding_id), indent=2)
    if name == "codesheriff_apply_fix":
        from quality_gates.models import Finding
        from quality_gates.review.apply import apply_and_verify

        packed = finding_from_reports(_root(), str(args.get("id") or "") or None)
        row = packed.get("finding")
        if not isinstance(row, dict):
            return json.dumps(packed, indent=2)
        finding = Finding(
            gate=str(row.get("gate") or "review"),
            message=str(row.get("message") or ""),
            path=row.get("path"),
            line=row.get("line") if isinstance(row.get("line"), int) else None,
            rule=row.get("rule"),
            patch=row.get("patch"),
            suggestion=row.get("suggestion"),
            verify=row.get("verify"),
        )
        verified = apply_and_verify(_root(), finding)
        verified["id"] = row.get("id")
        return json.dumps(verified, indent=2)
    if name == "codesheriff_merge":
        argv = ["merge"]
        if args.get("base"):
            argv.extend(["--base", str(args["base"])])
        if args.get("verify") is True:
            argv.append("--verify")
        if args.get("verify") is False:
            argv.append("--no-verify")
        if args.get("siblings") is True:
            argv.append("--siblings")
        if args.get("siblings") is False:
            argv.append("--no-siblings")
        code = runner(argv)
        payload = remaining_from_reports(_root())
        payload["exit_code"] = code
        return json.dumps(payload, indent=2)
    if name == "codesheriff_fix":
        from quality_gates.autofix import run_autofix

        payload = run_autofix(_root(), apply_patches=args.get("patches") is not False)
        remaining = remaining_from_reports(_root())
        remaining["autofix"] = payload
        return json.dumps(remaining, indent=2)
    if name == "codesheriff_certify":
        payload = remaining_from_reports(_root())
        return json.dumps(payload.get("certificate") or payload, indent=2)
    if name == "codesheriff_pr_comments":
        argv = ["comments"]
        if args.get("fail"):
            argv.append("--fail")
        code = runner(argv)
        payload = remaining_from_reports(_root())
        payload["exit_code"] = code
        return json.dumps(payload, indent=2)
    if name == "codesheriff_status":
        import json as _json

        from quality_gates.status_payload import status_payload

        payload = status_payload(_root())
        if args.get("prompt"):
            return render_prompt(payload)
        if args.get("verbose"):
            return _json.dumps(payload, indent=2)
        return _json.dumps(
            {
                "green": payload.get("green"),
                "certificate_ready": (payload.get("certificate") or {}).get("ready"),
                "blocking_count": len(payload.get("blocking") or []),
                "warning_count": len(payload.get("warnings") or []),
                "next": (payload.get("playbook") or {})
                .get("next", {})
                .get("instruction"),
            },
            indent=2,
        )
    if name == "codesheriff_hooks":
        from quality_gates.status_payload import hooks_payload

        action = args.get("action", "status")
        result = hooks_payload(_root())
        if action == "install":
            import subprocess

            root_val = _root()
            precommit = root_val / ".pre-commit-config.yaml"
            if precommit.is_file():
                subprocess.run(
                    [
                        "pre-commit",
                        "install",
                        "--hook-type",
                        "pre-commit",
                        "--hook-type",
                        "pre-push",
                    ],
                    cwd=root_val,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                result["hooks"] = hooks_payload(root_val)["hooks"]
                result["installed"] = True
        if action == "uninstall":
            hooks_dir = _root() / ".git" / "hooks"
            for hook_file in ["pre-commit", "pre-push"]:
                hook_path = hooks_dir / hook_file
                if hook_path.exists():
                    hook_path.unlink()
            result["uninstalled"] = True
        return json.dumps(result, indent=2)
    if name == "codesheriff_agent":
        from quality_gates.status_payload import agent_payload

        action = args.get("action", "context")
        finding_id = args.get("id")
        result = agent_payload(_root(), action=action, finding_id=finding_id)
        if action == "next":
            result["next"] = (
                (result.get("status") or {}).get("playbook", {}).get("next", {})
            )
        if action == "loop":
            result["loop"] = "run codesheriff agent --stream"
        return json.dumps(result, indent=2)
    if name == "codesheriff_interact":
        from quality_gates.review.commands import help_text, parse_sheriff_command

        cmd = args.get("command")
        if cmd and cmd.startswith("/sheriff"):
            parsed = parse_sheriff_command(cmd)
            if parsed:
                return json.dumps(
                    {
                        "command": parsed.name,
                        "focus": parsed.focus,
                        "argument": parsed.argument,
                        "forces_review": parsed.forces_review,
                    },
                    indent=2,
                )
            return json.dumps(
                {"error": "invalid command", "help": help_text()}, indent=2
            )
        if not cmd:
            payload = remaining_from_reports(_root())
            return json.dumps(
                {
                    "mode": "interactive",
                    "green": payload.get("green"),
                    "ready": (payload.get("certificate") or {}).get("ready"),
                    "commands": [
                        "/sheriff review",
                        "/sheriff fix",
                        "/sheriff pause",
                        "/sheriff resume",
                    ],
                },
                indent=2,
            )
        return json.dumps({"command": cmd, "status": "unhandled"}, indent=2)
    if name == "codesheriff_ask":
        from quality_gates.review.index import answer_question

        question = str(args.get("question") or "").strip()
        if not question:
            return json.dumps({"error": "question is required"}, indent=2)
        result = answer_question(_root(), question)
        return json.dumps(result, indent=2)
    if name == "codesheriff_handoff":
        from quality_gates.review.index import get_agent_handoff_context

        finding_id = str(args.get("id") or "")
        path = str(args.get("path") or "")
        rule = str(args.get("rule") or "")

        if finding_id:
            packed = finding_from_reports(_root(), finding_id)
            row = packed.get("finding")
            if isinstance(row, dict):
                path = path or str(row.get("path") or "")
                rule = rule or str(row.get("rule") or "")

        result = get_agent_handoff_context(
            _root(),
            finding_path=path or None,
            finding_rule=rule or None,
        )
        return json.dumps(result, indent=2)
    return f"unknown tool {name}"


def _default_runner(argv: list[str]) -> int:
    import subprocess

    return subprocess.call([sys.executable, "-m", "quality_gates", *argv])


def _root():
    from quality_gates.paths import project_root

    return project_root()


def _ok(msg_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _read(stdin) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stdin.readline()
        if line == "":
            return None
        stripped = line.strip()
        if not stripped:
            break
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length") or "0")
    if length <= 0:
        return None
    raw = stdin.read(length)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _write(stdout, message: dict[str, Any]) -> None:
    raw = json.dumps(message, ensure_ascii=False)
    stdout.write(f"Content-Length: {len(raw.encode('utf-8'))}\r\n\r\n{raw}")
    stdout.flush()
