"""A fake code agent for tests (Faz 6), run as ``python fake_agent.py <mode>``.

Protocol of the ``generic`` agent kind: the prompt arrives on stdin, the working directory
is the task's workdir, the final message goes to stdout.

Modes:
- ``echo``: reports how many characters of prompt it received.
- ``flaky``: breaks ``calc.py`` on the first try, fixes it once the prompt has feedback.
- ``right``: fixes ``calc.py``.
- ``commit``: fixes ``calc.py`` and commits it (the diff must still be against the baseline).
- ``litter``: fixes ``calc.py`` and leaves a ``scratch.log`` behind (counts as its change).
- ``empty``: says nothing, exit code 0.
- ``fail``: exit code 3 with a message on stderr.
- ``cannot``: ``CANNOT_DO: <reason>``.
- ``hang``: starts a child process, writes both pids to ``$FAKE_AGENT_PIDS``, then sleeps.
- ``escape``: writes into ``$FAKE_AGENT_ESCAPE`` (a file outside the workdir), then fixes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

RIGHT = "def add(a, b):\n    return a + b\n"
WRONG = "def add(a, b):\n    return a * b\n"


def _write(name: str, text: str) -> None:
    Path(name).write_bytes(text.encode("utf-8"))


def main() -> int:
    mode = sys.argv[1]
    prompt = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    if mode == "echo":
        print(f"received {len(prompt)} chars")
    elif mode == "flaky":
        fixed = "Failed checks" in prompt
        _write("calc.py", RIGHT if fixed else WRONG)
        print("fixed add()" if fixed else "changed add()")
    elif mode == "right":
        _write("calc.py", RIGHT)
        print("fixed add()")
    elif mode == "commit":
        _write("calc.py", RIGHT)
        env = {**os.environ, "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b",
               "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@b"}  # fmt: skip
        subprocess.run(["git", "commit", "-qam", "agent commit"], check=True, env=env)
        print("fixed and committed")
    elif mode == "litter":
        _write("calc.py", RIGHT)
        _write("scratch.log", "agent notes\n")
        print("fixed add()")
    elif mode == "empty":
        pass
    elif mode == "fail":
        print("boom: not logged in", file=sys.stderr)
        return 3
    elif mode == "cannot":
        print("CANNOT_DO: the task needs a database")
    elif mode == "hang":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        Path(os.environ["FAKE_AGENT_PIDS"]).write_text(
            f"{os.getpid()} {child.pid}", encoding="utf-8"
        )
        time.sleep(600)
    elif mode == "escape":
        Path(os.environ["FAKE_AGENT_ESCAPE"]).write_bytes(b"written by the agent\n")
        _write("calc.py", RIGHT)
        print("fixed add()")
    else:
        print(f"unknown mode {mode}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
