"""Low-level GitHub API client: REST calls, App JWTs, and check runs.

Split out of ``github_app.py``; the public names are re-exported there so
existing imports keep working.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from quality_gates.github_comment import API_VERSION, pr_head_sha
from quality_gates.host import api_url
from quality_gates.identity import CHECK_NAME, USER_AGENT


def api_request(
    method: str, url: str, token: str, payload: dict[str, Any] | None = None
) -> tuple[int, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            parsed: Any
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {}
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"message": raw[:300]}
        return exc.code, parsed
    except urllib.error.URLError as exc:
        return 0, {"message": str(exc)}


def app_jwt(app_id: str, pem: str, *, now: int | None = None) -> str:
    issued = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iat": issued - 60, "exp": issued + 540, "iss": app_id}
    signing_input = (
        f"{_b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{_b64url(json.dumps(claims, separators=(',', ':')).encode())}"
    )
    signature = _rsa_sign(pem, signing_input.encode("ascii"))
    return f"{signing_input}.{_b64url(signature)}"


def installation_token(app_id: str, pem: str, installation_id: str) -> str:
    token_jwt = app_jwt(app_id, pem)
    status, data = api_request(
        "POST",
        api_url(f"/app/installations/{installation_id}/access_tokens"),
        token_jwt,
        {},
    )
    if status >= 300 or not isinstance(data, dict) or not data.get("token"):
        raise RuntimeError(f"installation token failed HTTP {status}: {data}")
    return str(data["token"])


def post_check(
    *,
    name: str = CHECK_NAME,
    status: str = "in_progress",
    conclusion: str | None = None,
    title: str = "",
    summary: str = "",
    details_url: str = "",
) -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    sha = pr_head_sha()
    if not token or not repo or not sha:
        return "skipped check run (need GITHUB_TOKEN, GITHUB_REPOSITORY, SHA)"
    payload: dict[str, Any] = {
        "name": name,
        "head_sha": sha,
        "status": status,
    }
    if details_url:
        payload["details_url"] = details_url
    if status == "completed":
        payload["conclusion"] = conclusion or "neutral"
    if title or summary:
        payload["output"] = {
            "title": (title or name)[:255],
            "summary": (summary or title or name)[:65535],
        }
    code, data = api_request(
        "POST", api_url(f"/repos/{repo}/check-runs"), token, payload
    )
    if 200 <= code < 300:
        return f"posted check run {name} ({status})"
    message = data.get("message") if isinstance(data, dict) else data
    return f"GitHub check run HTTP {code} ({message})"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _rsa_sign(pem: str, data: bytes) -> bytes:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
        handle.write(pem)
        path = handle.name
    try:
        result = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", path],
            input=data,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"openssl RS256 sign failed: {err}")
        return result.stdout
    finally:
        Path(path).unlink(missing_ok=True)
