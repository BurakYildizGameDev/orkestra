from __future__ import annotations

import re

import pytest

from orkestra import i18n
from orkestra.cli import _find_lang_arg, app

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    with pytest.raises(SystemExit) as exc_info:
        app(argv)
    captured = capsys.readouterr()
    code = exc_info.value.code
    # CI (GITHUB_ACTIONS) makes rich emit colors even when captured; compare plain text.
    out, err = _ANSI.sub("", captured.out), _ANSI.sub("", captured.err)
    return (code if isinstance(code, int) else 0), out, err


def test_help_english(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["--lang", "en", "--help"], capsys)
    assert code == 0
    assert "Budget-aware task dispatcher" in out
    assert "Show the version and exit." in out
    assert "--lang" in out


def test_help_turkish(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["--lang", "tr", "--help"], capsys)
    assert code == 0
    assert "bütçe farkındalıklı görev dağıtıcı" in out
    assert "Sürümü gösterir ve çıkar." in out


def test_help_lang_equals_form(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(["--lang=tr", "--help"], capsys)
    assert code == 0
    assert "Sürümü gösterir ve çıkar." in out


def test_help_language_from_env(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(i18n.LANG_ENV, "tr")
    _, out, _ = _run(["--help"], capsys)
    assert "Sürümü gösterir ve çıkar." in out


def test_no_args_shows_help(capsys: pytest.CaptureFixture[str]) -> None:
    _, out, err = _run([], capsys)
    assert "Budget-aware task dispatcher" in out + err


def test_unsupported_lang_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        app(["--lang", "xx"])
    assert exc_info.value.code == 2
    assert "Unsupported language 'xx'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--lang", "tr", "--help"], "tr"),
        (["--help", "--lang=en"], "en"),
        (["--lang"], None),
        (["--", "--lang", "tr"], None),
        (["--version"], None),
        (["--config", "c.yaml", "--lang", "tr", "ask", "hi"], "tr"),
        # a subcommand's own arguments never switch the language
        (["ask", "--lang=de"], None),
        (["ask", "hi", "--lang", "tr"], None),
        (["config", "show", "--lang", "tr"], None),
    ],
)
def test_find_lang_arg(argv: list[str], expected: str | None) -> None:
    assert _find_lang_arg(argv) == expected


@pytest.mark.parametrize("value", ["TR", "tr_TR", "tr-TR"])
def test_lang_is_normalized_like_the_env_var(
    value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = _run(["--lang", value, "--help"], capsys)
    assert code == 0
    assert "Sürümü gösterir ve çıkar." in out
