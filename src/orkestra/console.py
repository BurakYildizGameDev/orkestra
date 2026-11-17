"""Console streams, shared by the full CLI and the light entry point (``entry.py``)."""

from __future__ import annotations

import contextlib
import os
import sys


def safe_streams() -> None:
    """Redirected output is UTF-8; no stream ever crashes on text it cannot encode.

    Redirected output on Windows defaults to the ANSI code page (e.g. cp1254), but whoever
    reads a pipe or a file (Claude Code, Git Bash, an editor) expects UTF-8, so Turkish
    letters arrived broken (D-049). An explicit ``PYTHONIOENCODING`` still wins. A legacy
    console keeps its code page. Characters a stream cannot encode (an emoji on a legacy
    console, a git path decoded with ``surrogateescape``) become ``?`` instead of raising
    ``UnicodeEncodeError`` after a successful run; the full text is always in ``output.md``.
    """
    chosen = bool(os.environ.get("PYTHONIOENCODING"))
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        try:
            to_utf8 = encoding != "utf8" and not chosen and not stream.isatty()
        except (ValueError, OSError):
            continue  # detached or closed: leave it
        with contextlib.suppress(ValueError, OSError):
            if to_utf8:
                reconfigure(encoding="utf-8", errors="replace")
            else:
                reconfigure(errors="replace")


def read_stdin() -> str:
    """What another program pipes in, as UTF-8 whatever the console code page (Faz 13k)."""
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8", errors="replace")
    return sys.stdin.read()
