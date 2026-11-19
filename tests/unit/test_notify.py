"""Notifications: desktop (optional extra) and ntfy, never with content (Faz 12a, §21)."""

from __future__ import annotations

import sys
from typing import Any

import httpx
import pytest
import respx

from orkestra.config.schema import NotifyCfg
from orkestra.i18n import t
from orkestra.notify import notify

REAL_DESKTOP_SEND = notify.desktop_send  # captured before conftest swaps it out
REAL_NTFY_POST = notify.ntfy_post


class Recorder:
    def __init__(self, fail: BaseException | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.fail = fail

    def __call__(self, *args: Any) -> None:
        self.calls.append(args)
        if self.fail is not None:
            raise self.fail


def _states(deliveries: list[notify.Delivery]) -> dict[str, str]:
    return {d.channel: d.state for d in deliveries}


def test_the_message_is_only_the_counts() -> None:
    assert notify.counts_text(3, 1) == t("notify.counts", finished=3, failed=1)


def test_desktop_and_ntfy_both_get_the_same_short_text() -> None:
    desktop, post = Recorder(), Recorder()
    cfg = NotifyCfg(desktop=True, ntfy_topic_env="ORK_TOPIC")
    deliveries = notify.send(
        cfg,
        "Orkestra",
        "3 finished, 1 failed",
        environ={"ORK_TOPIC": "my-topic_1"},
        desktop=desktop,
        post=post,
    )
    assert _states(deliveries) == {"desktop": "sent", "ntfy": "sent"}
    assert desktop.calls == [("Orkestra", "3 finished, 1 failed")]
    assert post.calls == [("https://ntfy.sh/my-topic_1", "Orkestra", "3 finished, 1 failed")]


def test_a_missing_desktop_notifier_is_skipped_quietly() -> None:
    deliveries = notify.send(
        NotifyCfg(desktop=True),
        "Orkestra",
        "x",
        environ={},
        desktop=Recorder(ImportError("desktop_notifier")),
        post=Recorder(),
    )
    assert _states(deliveries) == {"desktop": "skipped"}
    assert deliveries[0].reason == "not_installed"


def test_the_real_desktop_sender_without_the_package_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "desktop_notifier", None)  # import -> ImportError
    deliveries = notify.send(
        NotifyCfg(desktop=True),
        "Orkestra",
        "x",
        environ={},
        desktop=REAL_DESKTOP_SEND,
        post=Recorder(),
    )
    assert _states(deliveries) == {"desktop": "skipped"}


def test_desktop_off_and_no_topic_sends_nothing() -> None:
    desktop, post = Recorder(), Recorder()
    assert (
        notify.send(NotifyCfg(desktop=False), "T", "m", environ={}, desktop=desktop, post=post)
        == []
    )
    assert desktop.calls == [] and post.calls == []


def test_an_unset_topic_variable_is_skipped_and_its_value_never_shown() -> None:
    post = Recorder()
    cfg = NotifyCfg(desktop=False, ntfy_topic_env="ORK_TOPIC")
    deliveries = notify.send(cfg, "T", "m", environ={}, post=post)
    assert _states(deliveries) == {"ntfy": "skipped"} and deliveries[0].reason == "topic_unset"
    assert post.calls == []


@pytest.mark.parametrize("topic", ["a/b", "x?y=1", "../admin", "has space", "t" * 65])
def test_a_topic_that_is_not_a_plain_name_is_not_posted(topic: str) -> None:
    post = Recorder()
    cfg = NotifyCfg(desktop=False, ntfy_topic_env="ORK_TOPIC")
    deliveries = notify.send(cfg, "T", "m", environ={"ORK_TOPIC": topic}, post=post)
    assert _states(deliveries) == {"ntfy": "failed"} and deliveries[0].reason == "topic_invalid"
    assert post.calls == []


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("offline"),
        httpx.HTTPStatusError(
            "429", request=httpx.Request("POST", "https://ntfy.sh/x"), response=httpx.Response(429)
        ),
    ],
)
def test_a_failed_post_or_desktop_call_is_reported_not_raised(error: Exception) -> None:
    cfg = NotifyCfg(desktop=True, ntfy_topic_env="ORK_TOPIC")
    deliveries = notify.send(
        cfg,
        "T",
        "m",
        environ={"ORK_TOPIC": "topic"},
        desktop=Recorder(OSError("no bus")),
        post=Recorder(error),
    )
    assert _states(deliveries) == {"desktop": "failed", "ntfy": "failed"}


def test_lines_name_the_variable_not_the_topic() -> None:
    deliveries = [
        notify.Delivery("ntfy", "skipped", "topic_unset"),
        notify.Delivery("desktop", "skipped", "not_installed"),
    ]
    text = "\n".join(notify.delivery_lines(deliveries, NotifyCfg(ntfy_topic_env="ORK_TOPIC")))
    assert "ORK_TOPIC" in text and "orkestra-cli[notify]" in text


def test_the_real_ntfy_post_sends_a_title_with_non_ascii_letters() -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("https://ntfy.sh/my-topic").mock(return_value=httpx.Response(200))
        REAL_NTFY_POST("https://ntfy.sh/my-topic", "Orkestra kuyruğu", "2 bitti, 0 başarısız")
    request = route.calls.last.request
    assert request.url.params["title"] == "Orkestra kuyruğu"
    assert request.content.decode("utf-8") == "2 bitti, 0 başarısız"


def test_skipped_items_are_counted_in_the_message() -> None:
    assert notify.counts_text(3, 1, skipped=2) == t(
        "notify.counts_skipped", finished=3, failed=1, skipped=2
    )
    assert notify.counts_text(3, 1, skipped=0) == t("notify.counts", finished=3, failed=1)


@pytest.mark.parametrize("value", ["my-topic", "has space", "1STARTS", "a.b"])
def test_a_value_that_is_not_a_variable_name_is_never_used_or_shown(value: str) -> None:
    post = Recorder()
    cfg = NotifyCfg(desktop=False, ntfy_topic_env=value)
    deliveries = notify.send(cfg, "T", "m", environ={value: "topic"}, post=post)
    assert _states(deliveries) == {"ntfy": "failed"} and deliveries[0].reason == "env_invalid"
    assert post.calls == []
    assert value not in "\n".join(notify.delivery_lines(deliveries, cfg))
    assert not notify.is_variable_name(value) and notify.is_variable_name("ORK_TOPIC_2")


# --- notify.ntfy_url (düzeltme-fable a, D-104) ------------------------------------------


@pytest.mark.parametrize(
    "base", ["https://push.example.org", "https://push.example.org/", "https://h.example/sub"]
)
def test_a_custom_ntfy_server_gets_the_post(base: str) -> None:
    post = Recorder()
    cfg = NotifyCfg(desktop=False, ntfy_topic_env="ORK_TOPIC", ntfy_url=base)
    deliveries = notify.send(cfg, "T", "m", environ={"ORK_TOPIC": "topic1"}, post=post)
    assert _states(deliveries) == {"ntfy": "sent"}
    assert post.calls == [(base.rstrip("/") + "/topic1", "T", "m")]


def test_the_default_server_is_unchanged() -> None:
    assert NotifyCfg().ntfy_url == "https://ntfy.sh"


@pytest.mark.parametrize(
    "url",
    ["http://localhost:8080", "http://127.0.0.1", "http://192.168.1.20:80", "http://[::1]:9"],
)
def test_plain_http_is_allowed_only_for_a_local_address(url: str) -> None:
    assert NotifyCfg(ntfy_url=url).ntfy_url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://push.example.org",
        "http://8.8.8.8",
        "ftp://push.example.org",
        "push.example.org",
        "https:///no-host",
        "https://user:pw@push.example.org",
        "https://push.example.org?x=1",
    ],
)
def test_a_remote_plain_http_or_odd_url_is_refused_without_echoing_it(url: str) -> None:
    from pydantic import ValidationError

    from orkestra.config.loader import format_validation_error

    with pytest.raises(ValidationError) as caught:
        NotifyCfg(ntfy_url=url)
    lines = format_validation_error(caught.value)
    assert lines and all(url not in line for line in lines)
