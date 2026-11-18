"""The console script (Faz 13k): ``statusline`` and its hook skip the heavy CLI import."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from orkestra import entry

PROBE = """
import sys
from orkestra import entry
try:
    entry.main(sys.argv[1:])
except SystemExit as exc:
    code = exc.code
heavy = sorted(m for m in ("orkestra.cli", "openai", "orkestra.doctor") if m in sys.modules)
print(json.dumps({"code": code, "heavy": heavy}), file=sys.stderr)
"""


def _probe(tmp_path: Path, args: list[str], stdin: str) -> tuple[str, dict[str, object]]:
    env = {**os.environ, "ORKESTRA_HOME": str(tmp_path / "home"), "ORKESTRA_LANG": "en"}
    done = subprocess.run(
        [sys.executable, "-c", "import json\n" + PROBE, *args],
        input=stdin.encode("utf-8"), capture_output=True, env=env, timeout=60, check=False,
    )  # fmt: skip
    report = json.loads(done.stderr.decode("utf-8").strip().splitlines()[-1])
    return done.stdout.decode("utf-8"), report


def test_the_status_line_takes_the_light_path(tmp_path: Path) -> None:
    payload = json.dumps({"rate_limits": {"five_hour": {"used_percentage": 33}}})
    out, report = _probe(tmp_path, ["statusline"], payload)
    assert out.strip() == "Claude 5h 33%"
    assert report == {"code": 0, "heavy": []}


def test_the_hook_takes_the_light_path(tmp_path: Path) -> None:
    out, report = _probe(tmp_path, ["statusline", "hook"], '{"hook_event_name": "Stop"}')
    assert out == "" and report == {"code": 0, "heavy": []}


def test_anything_else_goes_to_the_full_cli(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as exc_info:
        entry.main(["statusline", "--help"])
    assert exc_info.value.code == 0
    assert "hook" in capsys.readouterr().out
