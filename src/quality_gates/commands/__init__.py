"""Auto-discovered extension commands.

Each module in this package may define:

- ``register(sub)``: add argparse subparsers (called during CLI construction).
- ``handle(args, root, config)``: return an int exit code when the module owns
  ``args.command``, otherwise return ``None`` to pass to the next module.

Modules are discovered with :mod:`pkgutil`, so adding a new command is a
single new file — no edits to ``cli.py`` or this package are required.
"""
