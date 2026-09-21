"""Parse /sheriff reviewer commands from pull-request comments."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quality_gates.config import QualityConfig

PREFIX = "/sheriff"
COMMANDS = (
    "review",
    "summary",
    "explain",
    "check",
    "fix",
    "ignore",
    "suppress",
    "why",
    "pause",
    "resume",
    "full",
    "help",
)
CHECK_FOCUSES = ("security", "tests", "migration", "architecture")
HELP = """The Code Sheriff commands (prefix `/sheriff` so they do not collide with other bots):

- `/sheriff review` — full review
- `/sheriff summary` — PR summary only
- `/sheriff explain [question]` — explain the diff
- `/sheriff check security` — security-focused review
- `/sheriff check tests` — test-gap review
- `/sheriff fix` — generate fix suggestions / a separate fix PR
- `/sheriff suppress <finding-id> [reason]` — accept a specific finding (committed)
- `/sheriff why <finding-id>` — show the evidence trail for a finding
- `/sheriff ignore <rule> [reason]` — suppress a finding with rationale
- `/sheriff pause` — pause automated review (writes .quality-reports/sheriff-paused)
- `/sheriff resume` — resume automated review (clears the paused flag)
- `/sheriff full` — force a full review vs incremental
- `/sheriff help` — this list
"""

PAUSED_FLAG = "sheriff-paused"


def paused_path(root: Path) -> Path:
    return root / ".quality-reports" / PAUSED_FLAG


def is_paused(root: Path) -> bool:
    return paused_path(root).is_file()


_LINE = re.compile(
    r"^/sheriff(?:\s+(?P<cmd>[a-z-]+))?(?:\s+(?P<rest>.+))?$",
    re.I | re.M,
)


@dataclass(frozen=True)
class SheriffCommand:
    name: str
    focus: str = ""
    argument: str = ""
    raw: str = ""

    @property
    def forces_review(self) -> bool:
        return self.name in {"review", "check", "explain", "fix", "summary", "full"}

    @property
    def verb(self) -> str:
        """Alias for :attr:`name` (stash-era ``SheriffRequest.verb`` compat)."""
        return self.name

    @property
    def finding_id(self) -> str:
        return self.argument.split()[0] if self.argument.split() else ""

    @property
    def reason(self) -> str:
        parts = self.argument.split(maxsplit=1)
        return parts[1] if len(parts) > 1 else ""


def parse_sheriff_command(body: str | None) -> SheriffCommand | None:
    text = (body or "").strip()
    if not text:
        return None
    match = _LINE.search(text)
    if not match:
        return None
    name = (match.group("cmd") or "help").lower()
    rest = (match.group("rest") or "").strip()
    if name not in COMMANDS:
        return SheriffCommand(name="help", argument=name, raw=text)
    if name == "check":
        focus = rest.split()[0].lower() if rest else "security"
        if focus not in CHECK_FOCUSES:
            focus = "security"
        leftover = (
            rest[len(focus) :].strip() if rest.lower().startswith(focus) else rest
        )
        return SheriffCommand(name="check", focus=focus, argument=leftover, raw=text)
    return SheriffCommand(name=name, argument=rest, raw=text)


def help_text() -> str:
    return HELP.strip() + "\n"


def run_sheriff(
    root: Path,
    config: QualityConfig,
    *,
    request: SheriffCommand | None,
    languages: list[str] | None = None,
    base: str | None = None,
    post: bool = False,
) -> tuple[int, str]:
    """Handle the P0 verbs: pause / resume / full (plus help / unknown).

    - ``pause`` writes ``.quality-reports/sheriff-paused`` (the review engine
      skips while present); ``resume`` clears it. ``full`` forces a full
      review vs incremental (``base`` ignored, no changed-path restriction).
    """
    if request is None:
        text = HELP + "\nNo sheriff command found.\n"
        return 2, text
    if request.name not in COMMANDS:
        text = HELP + f"\nUnknown verb `{request.name}`.\n"
        return 2, text
    if request.name == "help":
        return 0, HELP
    if request.name == "pause":
        flag = paused_path(root)
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("paused\n", encoding="utf-8")
        return 0, "Sheriff paused (wrote .quality-reports/sheriff-paused)."
    if request.name == "resume":
        flag = paused_path(root)
        if flag.is_file():
            flag.unlink()
        return 0, "Sheriff resumed (cleared .quality-reports/sheriff-paused)."
    if request.name == "full":
        from quality_gates.review.engine import run_review

        result = run_review(
            root,
            config,
            list(languages or []),
            base=None,
            post=post,
            full=True,
        )
        report = root / ".quality-reports" / "review.md"
        text = (
            report.read_text(encoding="utf-8")
            if report.is_file()
            else "review finished with no report"
        )
        return (0 if result.status == "pass" else 1), text
    return 2, HELP + f"\nVerb `{request.name}` is handled by its own command path.\n"
