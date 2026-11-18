"""The ``orkestra`` console script (Faz 13k, D-094).

Claude Code runs ``orkestra statusline`` after every message and ``orkestra statusline hook``
after every tool call. The full CLI imports every command (the openai SDK, doctor …), about a
second before anything runs; these two calls take a light path instead. Every other command,
and these two with any option (``--help``, ``--config`` …), goes to ``cli.app`` unchanged.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

LIGHT = (["statusline"], ["statusline", "hook"])


def main(argv: Sequence[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args in LIGHT:
        raise SystemExit(_light(args))
    from orkestra import cli

    cli.app(args)


def _light(args: list[str]) -> int:
    """Never fails: Claude Code shows whatever is printed, and a crash would only be noise."""
    from orkestra import console, i18n
    from orkestra.chief import limits
    from orkestra.config import loader
    from orkestra.config.schema import Config
    from orkestra.errors import OrkestraError
    from orkestra.state import db

    console.safe_streams()
    try:
        i18n.init_language(config=loader.read_language())
    except (OrkestraError, OSError, ValueError):  # the line must print even then
        i18n.set_language("en")
    text = console.read_stdin()
    now = db.local_now()

    def load() -> Config:
        return loader.load_config().config

    if args == ["statusline"]:
        print(limits.run_statusline(text, load_config=load, connect=db.connect, now=now))
    else:
        output = limits.run_hook(text, load_config=load, now=now)
        if output is not None:
            print(output)
    return 0
