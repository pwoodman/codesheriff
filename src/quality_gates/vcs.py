"""Minimal VCS provider seam so GitHub is a provider, not the architecture.

The App, comment, and annotation code only ever need a handful of operations:
find the PR, post a comment, post inline review comments, publish a check run,
and build a permalink to a line.  Everything else (webhooks, tokens, payload
shapes) is provider-specific glue.  Putting the small shared surface behind a
``VcsProvider`` protocol lets a GitLab/ADO implementation land without hunting
through ``github_*`` modules, and lets tests run against a fake host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from quality_gates.models import Finding


@dataclass(frozen=True)
class RepoRef:
    """A repository on a provider, e.g. ``github.com:acme/widgets``."""

    host: str
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True)
class PullRef:
    """A pull/merge request reviewed on ``repo``."""

    repo: RepoRef
    number: int
    head_sha: str
    base_ref: str = "main"


@dataclass(frozen=True)
class CheckOutcome:
    """What a provider reported after publishing a check, for the run summary."""

    url: str = ""
    state: str = ""
    detail: str = ""


@runtime_checkable
class VcsProvider(Protocol):
    """Operations the gate suite needs from a code host.

    Implementations must be safe to call when credentials are missing: return
    an explanatory ``CheckOutcome``/``str`` rather than raising, so a local run
    degrades to "skipped" instead of crashing the whole suite.
    """

    name: str

    def pull_from_env(self) -> PullRef | None:
        """The pull request this process is running for, if any."""

    def post_comment(self, pull: PullRef, body: str) -> CheckOutcome: ...

    def post_review(
        self, pull: PullRef, findings: list[Finding], summary: str = ""
    ) -> CheckOutcome: ...

    def publish_check(
        self,
        pull: PullRef,
        *,
        name: str,
        status: str,
        conclusion: str | None = None,
        title: str = "",
        summary: str = "",
        details_url: str = "",
    ) -> CheckOutcome: ...

    def blob_url(self, pull: PullRef, path: str, line: int | None = None) -> str: ...


def split_repo(slug: str) -> tuple[str, str]:
    """``owner/name`` → ``(owner, name)``; tolerant of a full URL."""
    text = slug.strip().rstrip("/")
    if "://" in text:
        text = text.split("://", 1)[1]
    parts = [part for part in text.split("/") if part]
    if len(parts) >= 3:
        return parts[-2], parts[-1]
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", text


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


class GitHubProvider:
    """GitHub implementation. The only provider that ships today."""

    name = "github"

    def __init__(self, *, token: str = "", repo: str = "", pr: object = None) -> None:
        from quality_gates.host import html_base

        self.token = token or _env("GITHUB_TOKEN", "GH_TOKEN")
        self.repo_slug = repo or os.environ.get("GITHUB_REPOSITORY", "")
        self.pr_number = pr
        self.host = html_base()

    def pull_from_env(self) -> PullRef | None:
        from quality_gates.github_comment import pr_head_sha

        pr = self.pr_number
        if pr is None:
            from quality_gates.github_comment import pr_number

            pr = pr_number()
        if not pr or not self.repo_slug:
            return None
        owner, name = split_repo(self.repo_slug)
        if not owner:
            return None
        head = pr_head_sha() or ""
        base = os.environ.get("GITHUB_BASE_REF") or "main"
        return PullRef(
            repo=RepoRef(host=self.host, owner=owner, name=name),
            number=int(pr),
            head_sha=head,
            base_ref=base,
        )

    def post_comment(self, pull: PullRef, body: str) -> CheckOutcome:
        from quality_gates.github_comment import post_pr_comment

        note = post_pr_comment(body)
        return CheckOutcome(state="comment", detail=note)

    def post_review(
        self, pull: PullRef, findings: list[Finding], summary: str = ""
    ) -> CheckOutcome:
        from quality_gates.github_comment import post_review

        notes = post_review(summary, findings)
        return CheckOutcome(state="review", detail="; ".join(notes))

    def publish_check(
        self,
        pull: PullRef,
        *,
        name: str,
        status: str,
        conclusion: str | None = None,
        title: str = "",
        summary: str = "",
        details_url: str = "",
    ) -> CheckOutcome:
        from quality_gates.github_app import post_check

        note = post_check(
            name=name,
            status=status,
            conclusion=conclusion,
            title=title,
            summary=summary,
            details_url=details_url,
        )
        return CheckOutcome(state=status, detail=note)

    def blob_url(self, pull: PullRef, path: str, line: int | None = None) -> str:
        ref = pull.head_sha or pull.base_ref or "HEAD"
        base = f"{self.host}/{pull.repo.slug}/blob/{ref}/{path.lstrip('/')}"
        return f"{base}#L{line}" if line else base


class _StubProvider:
    """Placeholder that documents intent without pretending to work."""

    def __init__(self, name: str) -> None:
        self.name = name

    def pull_from_env(self) -> PullRef | None:
        return None

    def post_comment(self, pull: PullRef, body: str) -> CheckOutcome:
        return CheckOutcome(
            state=self.name, detail=f"{self.name} provider not implemented"
        )

    def post_review(
        self, pull: PullRef, findings: list[Finding], summary: str = ""
    ) -> CheckOutcome:
        return CheckOutcome(
            state=self.name, detail=f"{self.name} provider not implemented"
        )

    def publish_check(self, pull: PullRef, **kwargs: Any) -> CheckOutcome:
        return CheckOutcome(
            state=self.name, detail=f"{self.name} provider not implemented"
        )

    def blob_url(self, pull: PullRef, path: str, line: int | None = None) -> str:
        return ""


def provider_for(name: str | None = None) -> VcsProvider:
    """Resolve a provider by name or from the environment."""
    chosen = (name or os.environ.get("SHERIFF_VCS") or "github").strip().lower()
    if chosen in {"github", "gh", ""}:
        return GitHubProvider()
    if chosen in {"gitlab", "ado", "azure", "bitbucket"}:
        return _StubProvider(chosen)
    raise ValueError(f"unknown VCS provider: {chosen}")


def current_provider(name: str | None = None) -> VcsProvider:
    """Best-effort provider for the current process; falls back to GitHub."""
    try:
        return provider_for(name)
    except ValueError:
        return GitHubProvider()


__all__ = [
    "CheckOutcome",
    "GitHubProvider",
    "PullRef",
    "RepoRef",
    "VcsProvider",
    "current_provider",
    "provider_for",
    "split_repo",
]
