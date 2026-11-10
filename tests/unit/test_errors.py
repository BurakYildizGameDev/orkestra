from __future__ import annotations

import pytest

from orkestra import errors
from orkestra.errors import ExitCode, exit_code_for


def test_exit_code_values_match_readme_table() -> None:
    assert {code.name: int(code) for code in ExitCode} == {
        "OK": 0,
        "TASK_FAILED": 1,
        "USAGE": 2,
        "NO_PROVIDER": 3,
        "CONSENT_REQUIRED": 4,
        "CONFLICT": 5,
        "INTERNAL": 10,
    }


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (errors.TaskFailed("x"), 1),
        (errors.ConfigError("x"), 2),
        (errors.UsageError("x"), 2),
        (errors.NoProviderAvailable("x"), 3),
        (errors.ConsentRequired("x"), 4),
        (errors.WorkspaceConflict("x"), 5),
        (errors.InternalError("x"), 10),
        (errors.OrkestraError("x"), 10),
        (errors.ProviderAuthError("x"), 3),
        (errors.ProviderRateLimit("x", retry_after=1.5), 3),
        (errors.ProviderTransient("x"), 3),
        (errors.ContextTooLong("x"), 3),
        (errors.ProviderBadOutput("x"), 3),
        (errors.ProviderUnavailable("x"), 3),
        (ValueError("boom"), 10),
        (KeyError("boom"), 10),
    ],
)
def test_exit_code_for(exc: BaseException, expected: int) -> None:
    assert exit_code_for(exc) == expected


@pytest.mark.parametrize(
    "cls",
    [
        errors.ProviderAuthError,
        errors.ProviderRateLimit,
        errors.ProviderTransient,
        errors.ContextTooLong,
        errors.ProviderBadOutput,
        errors.ProviderUnavailable,
    ],
)
def test_provider_errors_share_base(cls: type[errors.ProviderError]) -> None:
    assert issubclass(cls, errors.ProviderError)
    assert issubclass(cls, errors.OrkestraError)


def test_rate_limit_keeps_retry_after() -> None:
    assert errors.ProviderRateLimit("slow down", retry_after=12.0).retry_after == 12.0
    assert errors.ProviderRateLimit("slow down").retry_after is None


def test_message_is_kept() -> None:
    exc = errors.ConfigError("bad tier")
    assert exc.message == "bad tier"
    assert str(exc) == "bad tier"


def test_cli_maps_orkestra_error_to_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from orkestra import cli

    def failing_app() -> object:
        def run(**_: object) -> None:
            raise errors.ConsentRequired("enable it first")

        return run

    monkeypatch.setattr(cli, "build_app", failing_app)
    with pytest.raises(SystemExit) as exc_info:
        cli.app([])
    assert exc_info.value.code == 4
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Error: enable it first" in captured.err


def test_cli_maps_unexpected_error_to_10(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from orkestra import cli

    def failing_app() -> object:
        def run(**_: object) -> None:
            raise RuntimeError("kaboom")

        return run

    monkeypatch.setattr(cli, "build_app", failing_app)
    with pytest.raises(SystemExit) as exc_info:
        cli.app([])
    assert exc_info.value.code == 10
    assert "RuntimeError: kaboom" in capsys.readouterr().err


def test_internal_error_handler_survives_a_broken_catalog(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from orkestra import cli

    def failing_app() -> object:
        def run(**_: object) -> None:
            raise RuntimeError("kaboom")

        return run

    def broken_t(*_: object, **__: object) -> str:
        raise errors.TranslationError("catalog is broken")

    monkeypatch.setattr(cli, "build_app", failing_app)
    monkeypatch.setattr(cli, "t", broken_t)
    with pytest.raises(SystemExit) as exc_info:
        cli.app([])
    assert exc_info.value.code == 10
    assert "Unexpected internal error: RuntimeError: kaboom" in capsys.readouterr().err


@pytest.mark.parametrize("as_json", [False, True])
def test_error_without_message_names_the_error(
    as_json: bool, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from orkestra import cli

    def failing_app() -> object:
        def run(**_: object) -> None:
            raise errors.ConsentRequired()

        return run

    monkeypatch.setattr(cli, "build_app", failing_app)
    with pytest.raises(SystemExit) as exc_info:
        cli.app(["--json"] if as_json else [])
    assert exc_info.value.code == 4
    captured = capsys.readouterr()
    if as_json:
        assert json.loads(captured.out)["error"]["message"] == "ConsentRequired (no details)"
    else:
        assert "Error: ConsentRequired (no details)" in captured.err


def test_translation_error_is_internal() -> None:
    assert exit_code_for(errors.TranslationError("x")) == 10
