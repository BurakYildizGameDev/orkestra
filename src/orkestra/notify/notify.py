"""Notifications: desktop (``desktop-notifier``) and ntfy (Faz 12a, Mimari §21).

The text is only the counts ("3 finished, 1 failed"): no task text, code, paths or secrets,
because an ntfy topic is readable by anyone who guesses its name. The topic itself lives in
the environment variable that ``notify.ntfy_topic_env`` names and is never printed.

A notification never fails the command: ``desktop-notifier`` is an optional extra
(``orkestra-cli[notify]``) and is skipped quietly when missing; any other failure is a
``failed`` delivery the caller may show.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from orkestra.config.schema import NotifyCfg
from orkestra.i18n import t
from orkestra.state import db, forecast, health

NTFY_URL = "https://ntfy.sh/{topic}"
TIMEOUT_S = 10.0
EXTRA = "orkestra-cli[notify]"
_TOPIC = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_VARIABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

Channel = Literal["desktop", "ntfy"]
State = Literal["sent", "skipped", "failed"]
DesktopSender = Callable[[str, str], Any]  # title, message
Poster = Callable[[str, str, str], Any]  # url, title, message


@dataclass(frozen=True)
class Delivery:
    channel: Channel
    state: State
    reason: str | None = None  # not_installed | topic_unset | topic_invalid | env_invalid | …


def is_variable_name(value: str) -> bool:
    return bool(_VARIABLE.match(value))


def counts_text(finished: int, failed: int, *, skipped: int = 0) -> str:
    if skipped:
        return t("notify.counts_skipped", finished=finished, failed=failed, skipped=skipped)
    return t("notify.counts", finished=finished, failed=failed)


def desktop_send(title: str, message: str) -> None:
    """Show a desktop notification; ``ImportError`` when the extra is not installed."""
    module: Any = importlib.import_module("desktop_notifier")

    async def show() -> None:
        notifier = module.DesktopNotifier(app_name="Orkestra")
        await asyncio.wait_for(notifier.send(title=title, message=message), TIMEOUT_S)

    asyncio.run(show())


def ntfy_post(url: str, title: str, message: str) -> None:
    """The title goes in ntfy's ``title`` query parameter: an HTTP header is ASCII only, and
    the translated titles are not ("Orkestra kuyruğu")."""
    response = httpx.post(
        url, params={"title": title}, content=message.encode("utf-8"), timeout=TIMEOUT_S
    )
    response.raise_for_status()


def send(
    config: NotifyCfg,
    title: str,
    message: str,
    *,
    environ: Mapping[str, str] | None = None,
    desktop: DesktopSender | None = None,
    post: Poster | None = None,
) -> list[Delivery]:
    """Send to every configured channel; nothing here raises."""
    env = os.environ if environ is None else environ
    desktop = desktop or desktop_send
    post = post or ntfy_post
    deliveries: list[Delivery] = []
    if config.desktop:
        deliveries.append(_send_desktop(desktop, title, message))
    if config.ntfy_topic_env and not is_variable_name(config.ntfy_topic_env):
        # Probably the topic itself, typed where the variable's name goes: never use or show it.
        deliveries.append(Delivery("ntfy", "failed", "env_invalid"))
    elif config.ntfy_topic_env:
        deliveries.append(
            _send_ntfy(post, env.get(config.ntfy_topic_env, "").strip(), title, message)
        )
    return deliveries


def _send_desktop(desktop: DesktopSender, title: str, message: str) -> Delivery:
    try:
        desktop(title, message)
    except ImportError:
        return Delivery("desktop", "skipped", "not_installed")
    except Exception as exc:  # a missing notification daemon must not fail the command
        return Delivery("desktop", "failed", type(exc).__name__)
    return Delivery("desktop", "sent")


def _send_ntfy(post: Poster, topic: str, title: str, message: str) -> Delivery:
    if not topic:
        return Delivery("ntfy", "skipped", "topic_unset")
    if not _TOPIC.match(topic):
        return Delivery("ntfy", "failed", "topic_invalid")
    try:
        post(NTFY_URL.format(topic=topic), title, message)
    except Exception as exc:  # offline, rate limited: the work itself is done
        return Delivery("ntfy", "failed", type(exc).__name__)
    return Delivery("ntfy", "sent")


def delivery_lines(deliveries: list[Delivery], config: NotifyCfg) -> list[str]:
    """One line per channel; names the variable, never the topic."""
    lines: list[str] = []
    for item in deliveries:
        if item.reason == "not_installed":
            text = t("notify.state.not_installed", extra=EXTRA)
        elif item.reason == "topic_unset":
            text = t("notify.state.topic_unset", env=config.ntfy_topic_env or "-")
        elif item.reason == "env_invalid":
            text = t("notify.state.env_invalid")
        elif item.reason == "topic_invalid":
            text = t("notify.state.topic_invalid", env=config.ntfy_topic_env or "-")
        elif item.state == "sent":
            text = t("notify.state.sent")
        else:
            text = t("notify.state.failed", reason=item.reason or "-")
        lines.append(t("notify.line", channel=item.channel, text=text))
    return lines


def send_batch(
    config: NotifyCfg, results: int, ok: int, *, paused: Sequence[health.Health] = (),
    low: Sequence[forecast.Forecast] = (),
) -> list[Delivery]:  # fmt: skip
    """``batch --notify``: how many tasks ended and how many did not end ok, the providers
    whose quota ran out during the batch (``batch.quota_pauses``) and those running low."""
    message = with_quota(counts_text(results, results - ok), paused, low=low)
    return send(config, t("notify.title.batch"), message)


def with_quota(
    message: str, paused: Sequence[health.Health], *, low: Sequence[forecast.Forecast] = ()
) -> str:
    """The counts, plus one line naming the providers paused for quota (Faz 13f) and one
    naming those running low (Faz 13k): only names, times and counts, nothing of the work."""
    now = db.local_now()
    names = ", ".join(
        f"{h.provider} ({health.until_text(h.open_until, now)})" if h.open_until else h.provider
        for h in paused
    )
    if names:
        message = f"{message}\n{t('notify.quota', providers=names)}"
    if low:
        message += "\n" + t("notify.quota_low", providers=", ".join(map(forecast.describe, low)))
    return message


def any_sent(deliveries: list[Delivery]) -> bool:
    return any(d.state == "sent" for d in deliveries)
