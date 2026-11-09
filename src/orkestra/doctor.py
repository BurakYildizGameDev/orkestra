"""``orkestra doctor``: diagnose config, providers, keys and tools.

Key values are never read into messages: only whether the variable is set.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from orkestra.config.loader import load_config
from orkestra.config.schema import (
    CliAgentProvider,
    Config,
    OllamaProvider,
    OpenAICompatProvider,
    Provider,
)
from orkestra.errors import ConfigError, ProviderError
from orkestra.i18n import t
from orkestra.providers import pricing
from orkestra.providers.base import CompletionRequest
from orkestra.providers.ollama import OllamaChat, has_model
from orkestra.providers.openai_compat import OpenAICompatChat
from orkestra.state import consent, db, health

CheckStatus = Literal["ok", "warn", "fail", "info"]
VERSION_TIMEOUT_S = 10
INFO_TOOLS = ("codex", "agy")


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[Check, ...]

    @property
    def ok(self) -> bool:
        return all(c.status != "fail" for c in self.checks)


Which = Callable[[str], str | None]
VersionProbe = Callable[[str], str | None]


def probe_version(executable: str) -> str | None:
    """First non-empty line of ``<executable> --version``, or ``None``."""
    try:
        proc = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERSION_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in (proc.stdout or proc.stderr or "").splitlines():
        if line.strip():
            return line.strip()
    return None


async def _check_ollama(name: str, cfg: OllamaProvider, *, warm: bool) -> list[Check]:
    chat = OllamaChat(name, cfg)
    check_name = f"provider:{name}"
    report = await chat.health()
    if not report.ok:
        message = report.error.message if report.error else t("doctor.unreachable")
        return [Check(check_name, "fail", message, {"type": "ollama", "url": cfg.base_url})]
    available = report.models or ()
    checks = [
        Check(
            check_name,
            "ok",
            t("doctor.ollama.ok", url=cfg.base_url, count=len(available)),
            {"type": "ollama", "url": cfg.base_url, "models": list(available)},
        )
    ]
    for spec in cfg.models:
        if not has_model(available, spec.id):
            checks.append(
                Check(
                    check_name,
                    "warn",
                    t("doctor.ollama.model_missing", model=spec.id),
                    {"model": spec.id, "hint": f"ollama pull {spec.id}"},
                )
            )
        elif warm:
            checks.append(await _warm(chat, spec.id, cfg.timeout_s or 600, check_name))
    return checks


async def _warm(chat: OllamaChat, model: str, timeout_s: int, check_name: str) -> Check:
    started = time.monotonic()
    try:
        await chat.complete(
            CompletionRequest(
                model=model,
                system="",
                user="Reply with OK.",
                max_output_tokens=1,
                timeout_s=timeout_s,
            )
        )
    except ProviderError as exc:
        return Check(check_name, "fail", exc.message, {"model": model, "warm": False})
    seconds = round(time.monotonic() - started, 1)
    return Check(
        check_name,
        "ok",
        t("doctor.ollama.warm", model=model, seconds=seconds),
        {"model": model, "warm": True, "seconds": seconds},
    )


async def _check_openai(
    name: str, cfg: OpenAICompatProvider, environ: Mapping[str, str]
) -> list[Check]:
    check_name = f"provider:{name}"
    chat = OpenAICompatChat(name, cfg, environ)
    checks: list[Check] = []
    if cfg.api_key_env is not None:
        present = chat.key_present()
        checks.append(
            Check(
                check_name,
                "ok" if present else "warn",
                t("doctor.key.present" if present else "doctor.key.missing", var=cfg.api_key_env),
                {"api_key_env": cfg.api_key_env, "present": present},
            )
        )
        if not present:
            return checks
    report = await chat.health()
    if not report.ok:
        message = report.error.message if report.error else t("doctor.unreachable")
        checks.append(Check(check_name, "fail", message, {"type": "openai_compat"}))
        return checks
    available = report.models or ()
    checks.append(
        Check(
            check_name,
            "ok",
            t("doctor.api.ok", url=cfg.base_url, count=len(available)),
            {"type": "openai_compat", "url": cfg.base_url},
        )
    )
    for spec in cfg.models:
        if available and spec.id not in available:
            checks.append(
                Check(
                    check_name,
                    "warn",
                    t("doctor.api.model_missing", model=spec.id),
                    {"model": spec.id},
                )
            )
    return checks


def _check_agent(
    name: str, cfg: CliAgentProvider, which: Which, probe: VersionProbe
) -> list[Check]:
    path = which(cfg.command)
    if path is None:
        return [
            Check(
                f"provider:{name}",
                "warn",
                t("doctor.tool.missing", command=cfg.command),
                {"type": "cli_agent", "command": cfg.command},
            )
        ]
    version = probe(path)
    return [
        Check(
            f"provider:{name}",
            "info",
            t("doctor.tool.found", command=cfg.command, version=version or "?"),
            {"type": "cli_agent", "path": path, "version": version},
        )
    ]


async def _check_provider(
    name: str,
    cfg: Provider,
    *,
    warm: bool,
    environ: Mapping[str, str],
    which: Which,
    probe: VersionProbe,
) -> list[Check]:
    if not cfg.enabled:
        return [
            Check(f"provider:{name}", "info", t("doctor.provider.disabled"), {"enabled": False})
        ]
    if isinstance(cfg, OllamaProvider):
        return await _check_ollama(name, cfg, warm=warm)
    if isinstance(cfg, OpenAICompatProvider):
        return await _check_openai(name, cfg, environ)
    return _check_agent(name, cfg, which, probe)


def _state_checks(providers: Mapping[str, Provider]) -> list[Check]:
    """Consent and circuit breaker state from state.db."""
    checks: list[Check] = []
    now = db.local_now()
    with closing(db.connect()) as conn:
        for name, cfg in providers.items():
            if not cfg.enabled:
                continue
            current = consent.state(conn, name, cfg)
            if current != "granted":
                checks.append(
                    Check(
                        f"provider:{name}",
                        "warn",
                        t(f"doctor.consent.{current}"),
                        {"consent": current, "hint": f"orkestra providers enable {name}"},
                    )
                )
            state = health.get(conn, name)
            if state.is_open(now):
                until = state.open_until.isoformat() if state.open_until else None
                checks.append(
                    Check(
                        f"provider:{name}",
                        "warn",
                        t(
                            "doctor.circuit_open",
                            until=state.open_until.strftime("%H:%M") if state.open_until else "?",
                            error=state.last_error or "-",
                        ),
                        {"open_until": until, "failures": state.consecutive_failures},
                    )
                )
    return checks


async def _price_checks(config: Config, environ: Mapping[str, str]) -> list[Check]:
    """A ``daily_usd`` limit needs a price; refresh provider prices and report gaps."""
    targets = {
        name: cfg
        for name, cfg in config.providers.items()
        if cfg.enabled and pricing.needs_price(cfg)
    }
    if not targets:
        return []
    cache = await pricing.refresh(config, db.local_now(), environ=environ, force=True)
    checks: list[Check] = []
    with closing(db.connect()) as conn:
        for name, cfg in targets.items():
            for model in getattr(cfg, "models", []):
                price = pricing.resolve(name, cfg, model, conn=conn, cache=cache)
                if price is None:
                    checks.append(
                        Check(
                            f"provider:{name}",
                            "warn",
                            t("doctor.price.missing", model=model.id),
                            {"model": model.id, "price": None},
                        )
                    )
                elif price.source != "config":
                    checks.append(
                        Check(
                            f"provider:{name}",
                            "info",
                            t(
                                f"doctor.price.{price.source}",
                                model=model.id,
                                input=f"{price.input_per_mtok:g}",
                                output=f"{price.output_per_mtok:g}",
                            ),
                            {"model": model.id, "price_source": price.source},
                        )
                    )
    return checks


def _check_tool(tool: str, which: Which, probe: VersionProbe, *, required: bool) -> Check:
    path = which(tool)
    if path is None:
        status: CheckStatus = "fail" if required else "info"
        return Check(f"tool:{tool}", status, t("doctor.tool.missing", command=tool), {})
    version = probe(path)
    return Check(
        f"tool:{tool}",
        "ok" if required else "info",
        t("doctor.tool.found", command=tool, version=version or "?"),
        {"path": path, "version": version},
    )


async def run_doctor(
    *,
    config_flag: Path | None = None,
    warm: bool = False,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    which: Which = shutil.which,
    probe: VersionProbe = probe_version,
) -> DoctorReport:
    env = os.environ if environ is None else environ
    checks: list[Check] = []
    try:
        loaded = load_config(config_flag, cwd, env)
    except ConfigError as exc:
        checks.append(Check("config", "fail", exc.message, {"details": list(exc.details)}))
        loaded = None
    if loaded is not None:
        checks.append(
            Check(
                "config",
                "ok",
                t("doctor.config.ok"),
                {"sources": [str(s.path) for s in loaded.sources]},
            )
        )
        if not loaded.config.providers:
            checks.append(Check("config", "warn", t("select.no_providers")))
        for name, cfg in loaded.config.providers.items():
            checks.extend(
                await _check_provider(name, cfg, warm=warm, environ=env, which=which, probe=probe)
            )
        checks.extend(_state_checks(loaded.config.providers))
        checks.extend(await _price_checks(loaded.config, env))
    checks.append(_check_tool("git", which, probe, required=True))
    configured_commands = (
        {getattr(c, "command", None) for c in loaded.config.providers.values()} if loaded else set()
    )
    for tool in INFO_TOOLS:
        if tool not in configured_commands:
            checks.append(_check_tool(tool, which, probe, required=False))
    return DoctorReport(tuple(checks))
