"""GitLab merge-request review stub (P2).

Mirrors :mod:`quality_gates.github_comment` using only stdlib ``urllib``.
Reads ``GITLAB_TOKEN`` (falls back to ``CI_JOB_TOKEN``), ``CI_MERGE_REQUEST_IID``,
``CI_PROJECT_ID``, and ``CI_API_V4_URL`` (default ``https://gitlab.com/api/v4``).

Optional wiring from ``src/quality_gates/gates/review.py`` (P0-owned,
intentionally *not* edited here to avoid conflicts)::

    from quality_gates.review.gitlab import maybe_post_gitlab_review
    ...
    notes.extend(maybe_post_gitlab_review(body, findings))

``maybe_post_gitlab_review`` returns ``[]`` when GitLab env is absent, so the
GitHub path is never affected. Every public function is no-crash: without env
or on any HTTP error it returns a human-readable note instead of raising.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from quality_gates.models import Finding

DEFAULT_API_URL = "https://gitlab.com/api/v4"


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def gitlab_env_present() -> bool:
    """Return True when a GitLab MR note post is fully configured."""
    token = _env("GITLAB_TOKEN") or _env("CI_JOB_TOKEN")
    return bool(token and _env("CI_MERGE_REQUEST_IID") and _env("CI_PROJECT_ID"))


def _creds() -> tuple[str, str, str, str] | None:
    token = _env("GITLAB_TOKEN") or _env("CI_JOB_TOKEN")
    project = _env("CI_PROJECT_ID")
    iid = _env("CI_MERGE_REQUEST_IID")
    api = _env("CI_API_V4_URL") or _env("GITLAB_API_URL") or DEFAULT_API_URL
    if not (token and project and iid):
        return None
    return (token, api.rstrip("/"), project, iid)


def post_gitlab_note(body: str, *, timeout: int = 30) -> str:
    """Post ``body`` as an MR note. Returns a status string, never raises."""
    creds = _creds()
    if creds is None:
        return (
            "skipped GitLab note (need GITLAB_TOKEN/CI_JOB_TOKEN, "
            "CI_PROJECT_ID, CI_MERGE_REQUEST_IID)"
        )
    token, api, project, iid = creds
    url = (
        f"{api}/projects/{urllib.parse.quote(project, safe='')}"
        f"/merge_requests/{urllib.parse.quote(iid, safe='')}/notes"
    )
    payload = json.dumps({"body": body[:1_000_000]}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        return f"GitLab note returned HTTP {exc.code}"
    except Exception as exc:  # stub must never crash the gate
        return f"skipped GitLab note ({exc})"
    if 200 <= status < 300:
        return f"posted note on MR !{iid}"
    return f"GitLab note returned HTTP {status}"


def post_gitlab_review(
    body: str,
    findings: list[Finding] | None = None,
    *,
    timeout: int = 30,
) -> list[str]:
    """Post a review summary (plus finding bullets) to the GitLab MR.

    ``findings`` are rendered inline as ``- path:line message`` lines so the
    note is useful without the GitHub inline-comment API. Never raises;
    without env returns a single ``skipped ...`` note.
    """
    notes: list[str] = []
    if findings:
        bullets = "\n".join(
            f"- `{item.path or 'repo'}:{item.line or '?'} [{item.severity}] "
            f"{item.message[:300]}"
            for item in findings[:25]
        )
        full = f"{body.rstrip()}\n\n**Findings ({len(findings)})**\n{bullets}"
    else:
        full = body
    notes.append(post_gitlab_note(full, timeout=timeout))
    return notes


def maybe_post_gitlab_review(
    body: str,
    findings: list[Finding] | None = None,
    **kwargs: Any,
) -> list[str]:
    """Post to GitLab only when GitLab env is present, else return ``[]``.

    This is the safe wiring point for ``gates/review.py``: with no GitLab env
    it is a no-op, so the GitHub path is never broken or slowed.
    """
    if not gitlab_env_present():
        return []
    try:
        return post_gitlab_review(body, findings, **kwargs)
    except Exception as exc:  # never break the gate
        return [f"skipped GitLab review ({exc})"]
