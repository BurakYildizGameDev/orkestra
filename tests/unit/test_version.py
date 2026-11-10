from __future__ import annotations

import os
import subprocess
import sys

import pytest

from orkestra import __version__
from orkestra.cli import app


def test_version_value() -> None:
    assert __version__ == "0.0.1"


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        app(["--version"])
    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"orkestra {__version__}"


def test_python_m_orkestra_version() -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(
        [sys.executable, "-m", "orkestra", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"orkestra {__version__}"
