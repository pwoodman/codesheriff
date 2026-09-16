"""Poll the tree and rerun cheap gates. Stdlib only — no extra dependency."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from quality_gates.config import QualityConfig
from quality_gates.detect import iter_project_files

_NOTIFY_BINARIES = {
    "linux": ["notify-send"],
    "darwin": ["terminal-notifier", "osascript"],
}


def notify(title: str, message: str) -> bool:
    """Best-effort desktop notification; never raises, never blocks a loop.

    Set ``SHERIFF_NO_NOTIFY=1`` to silence it (CI and headless shells are
    auto-detected by the absence of a notification binary anyway).
    """
    if os.environ.get("SHERIFF_NO_NOTIFY"):
        return False
    import sys

    platform = "darwin" if sys.platform == "darwin" else "linux"
    for name in _NOTIFY_BINARIES.get(platform, []):
        binary = shutil.which(name)
        if not binary:
            continue
        if name == "osascript":
            args = [
                binary,
                "-e",
                f"display notification {message!r} with title {title!r}",
            ]
        elif name == "terminal-notifier":
            args = [binary, "-title", title, "-message", message]
        else:
            args = [binary, title, message]
        try:
            subprocess.run(args, timeout=5, check=False)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def snapshot(root: Path, config: QualityConfig) -> dict[str, tuple[int, int]]:
    """Return path → (mtime_ns, size) so same-second Windows writes still differ."""
    stamps: dict[str, tuple[int, int]] = {}
    for path in iter_project_files(root, config):
        try:
            info = path.stat()
            stamps[path.as_posix()] = (info.st_mtime_ns, info.st_size)
        except OSError:
            continue
    return stamps


def watch_loop(
    root: Path,
    config: QualityConfig,
    run: Callable[[], None],
    *,
    interval: float = 1.5,
    cycles: int | None = None,
) -> int:
    """Rerun ``run`` when project files change. ``cycles`` is for tests."""
    last = snapshot(root, config)
    seen = 0
    while cycles is None or seen < cycles:
        time.sleep(interval)
        current = snapshot(root, config)
        if current != last:
            last = current
            run()
        seen += 1
    return 0
