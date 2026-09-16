"""Extension-command loader bridging ``cli.py`` and ``quality_gates.commands``.

Keeps the main CLI module stable while new subcommands ship as standalone
modules under ``quality_gates/commands/``.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse

    from quality_gates.config import QualityConfig


def _iter_command_modules():
    import quality_gates.commands as commands_pkg

    for info in pkgutil.iter_modules(commands_pkg.__path__):
        yield importlib.import_module(f"{commands_pkg.__name__}.{info.name}")


def register_parsers(sub: argparse._SubParsersAction) -> None:
    for module in _iter_command_modules():
        register = getattr(module, "register", None)
        if register is not None:
            register(sub)


def dispatch(args: argparse.Namespace, root: Path, config: QualityConfig) -> int | None:
    for module in _iter_command_modules():
        handler = getattr(module, "handle", None)
        if handler is None:
            continue
        result: Any = handler(args, root, config)
        if result is not None:
            return int(result)
    return None
