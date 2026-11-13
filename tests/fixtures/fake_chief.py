"""A fake chief for the Faz 10b launch tests: records what it was given, then exits.

Run as ``python fake_chief.py <mode>``; the capture file is ``$FAKE_CHIEF_OUT`` and the exit
code is ``$FAKE_CHIEF_EXIT`` (default 0). Modes:

- ``arg``: writes the arguments after the mode (a JSON array) to the capture file.
- ``stdin``: writes everything it read from stdin to the capture file.
- ``file``: copies ``.orkestra/BRIEF.md`` from its working directory to the capture file.
- ``echo``: prints what it received to stdout (a human smoke test).

It never calls a real model and never touches the network.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: fake_chief.py <arg|stdin|file|echo> [args...]", file=sys.stderr)
        return 2
    mode = sys.argv[1]
    out = Path(os.environ["FAKE_CHIEF_OUT"]) if "FAKE_CHIEF_OUT" in os.environ else None
    if mode == "arg":
        text = json.dumps(sys.argv[2:])
        if out is not None:
            out.write_bytes(text.encode("utf-8"))
        print(text)
    elif mode == "stdin":
        text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        if out is not None:
            out.write_bytes(text.encode("utf-8"))
        print(f"received {len(text)} chars")
    elif mode == "file":
        text = Path(".orkestra/BRIEF.md").read_bytes().decode("utf-8")
        if out is not None:
            out.write_bytes(text.encode("utf-8"))
        print("read the brief file")
    elif mode == "echo":
        print(" ".join(sys.argv[2:]))
    else:
        print(f"unknown mode {mode}", file=sys.stderr)
        return 2
    return int(os.environ.get("FAKE_CHIEF_EXIT", "0"))


if __name__ == "__main__":
    raise SystemExit(main())
