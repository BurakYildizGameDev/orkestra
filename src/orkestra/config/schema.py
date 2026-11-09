"""Configuration models (Mimari §4.1)."""

from __future__ import annotations

import re
from pathlib import PureWindowsPath
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orkestra.i18n import t

CONFIG_VERSION = 1
PROVIDER_TYPES = ("ollama", "openai_compat", "cli_agent")
_PROVIDER_NAME = re.compile(r"^[a-z0-9_-]+$")
_AGENT_SUFFIXES = (".cmd", ".exe", ".bat", ".ps1")

Tier = Literal[1, 2, 3]
NonNegInt = Annotated[int, Field(ge=0)]
NonNegFloat = Annotated[float, Field(ge=0)]
PosInt = Annotated[int, Field(ge=1)]


class _Model(BaseModel):
    # Unknown keys are typos far more often than intent; reject them.
    model_config = ConfigDict(extra="forbid")


class Budget(_Model):
    daily_tokens: NonNegInt | None = None
    daily_usd: NonNegFloat | None = None
    daily_requests: NonNegInt | None = None
    daily_runs: NonNegInt | None = None


class ModelSpec(_Model):
    id: str
    tier: Tier
    context_window: PosInt = 8192
    max_output_tokens: PosInt | None = None
    price_per_mtok: dict[Literal["input", "output"], NonNegFloat] | None = None
    strengths: list[str] = Field(default_factory=list)
    priority: int = 0  # higher goes first within a tier


class ProviderBase(_Model):
    type: str
    enabled: bool = True
    local: bool = False
    concurrency: PosInt = 1
    timeout_s: PosInt | None = None
    budget: Budget = Field(default_factory=Budget)
    experimental: bool = False


class OllamaProvider(ProviderBase):
    type: Literal["ollama"]
    base_url: str = "http://localhost:11434"
    local: bool = True
    models: list[ModelSpec]


class OpenAICompatProvider(ProviderBase):
    type: Literal["openai_compat"]
    base_url: str
    api_key_env: str | None = None  # name of the environment variable, never the key
    extra_headers: dict[str, str] = Field(default_factory=dict)
    models: list[ModelSpec]


class CliAgentProvider(ProviderBase):
    type: Literal["cli_agent"]
    command: str  # "codex" | "agy" | absolute path
    kind: Literal["codex", "agy", "generic"] | None = None  # inferred from command if unset
    tier: Tier = 3
    model: str | None = None
    sandbox: Literal["read-only", "workspace-write"] = "workspace-write"
    extra_args: list[str] = Field(default_factory=list)

    @field_validator("sandbox", mode="before")
    @classmethod
    def _no_full_access(cls, value: Any) -> Any:
        if value == "danger-full-access":
            raise ValueError(t("config.validation.sandbox_danger"))
        return value

    @model_validator(mode="after")
    def _infer_kind(self) -> CliAgentProvider:
        if self.kind is None:
            # PureWindowsPath splits on both "/" and "\\".
            name = PureWindowsPath(self.command).name.lower()
            for suffix in _AGENT_SUFFIXES:
                name = name.removesuffix(suffix)
            self.kind = name if name in ("codex", "agy") else "generic"
        return self


Provider = Annotated[
    OllamaProvider | OpenAICompatProvider | CliAgentProvider, Field(discriminator="type")
]


class Profile(_Model):
    min_tier: Annotated[int, Field(ge=1, le=3)] = 1
    max_tier: Annotated[int, Field(ge=1, le=3)] = 3

    @model_validator(mode="after")
    def _ordered(self) -> Profile:
        if self.min_tier > self.max_tier:
            raise ValueError(
                t("config.validation.tier_order", min=self.min_tier, max=self.max_tier)
            )
        return self


class Security(_Model):
    block_secrets_to_remote: bool = True
    ignore_file: str = ".orkestraignore"
    max_api_edit_lines: PosInt = 400
    max_context_bytes: PosInt = 400_000


class Defaults(_Model):
    profile: str = "balanced"
    chief: str = "claude"
    timeout_s: PosInt = 300
    max_retries: NonNegInt = 2
    max_output_tokens: PosInt = 4096


class Chief(_Model):
    launch: list[str]
    prompt_mode: Literal["arg", "stdin", "file"] = "file"


class HandoffCfg(_Model):
    file: str = ".orkestra/HANDOFF.md"
    max_lines: PosInt = 200
    brief_max_lines: PosInt = 60
    stale_after_commits: PosInt = 5


class ReviewCfg(_Model):
    tier: Tier = 2
    auto: bool = False


class MapCfg(_Model):
    tier: Tier = 1
    privacy: Literal["normal", "local_only"] = "local_only"


class CacheCfg(_Model):
    enabled: bool = True
    ttl_days: NonNegInt = 14


class RoutingCfg(_Model):
    adaptive: bool = False
    min_samples: PosInt = 10


class EstimateCfg(_Model):
    confirm_above_usd: NonNegFloat | None = 0.50


class NotifyCfg(_Model):
    desktop: bool = True
    ntfy_topic_env: str | None = None  # name of the environment variable, not the topic


class QueueCfg(_Model):
    default_profile: str = "cheap"


def default_profiles() -> dict[str, Profile]:
    return {
        "cheap": Profile(min_tier=1, max_tier=1),
        "balanced": Profile(min_tier=1, max_tier=3),
        "quality": Profile(min_tier=2, max_tier=3),
    }


def default_chiefs() -> dict[str, Chief]:
    return {
        "claude": Chief(launch=["claude"], prompt_mode="arg"),
        "agy": Chief(launch=["agy"], prompt_mode="file"),
        "codex": Chief(launch=["codex"], prompt_mode="arg"),
    }


class Config(_Model):
    version: Literal[1]
    language: Literal["auto", "en", "tr", "de", "es", "fr"] = "auto"
    defaults: Defaults = Field(default_factory=Defaults)
    providers: dict[str, Provider] = Field(default_factory=dict)
    profiles: dict[str, Profile] = Field(default_factory=default_profiles)
    chiefs: dict[str, Chief] = Field(default_factory=default_chiefs)
    handoff: HandoffCfg = Field(default_factory=HandoffCfg)
    review: ReviewCfg = Field(default_factory=ReviewCfg)
    map: MapCfg = Field(default_factory=MapCfg)
    cache: CacheCfg = Field(default_factory=CacheCfg)
    routing: RoutingCfg = Field(default_factory=RoutingCfg)
    estimate: EstimateCfg = Field(default_factory=EstimateCfg)
    notify: NotifyCfg = Field(default_factory=NotifyCfg)
    queue: QueueCfg = Field(default_factory=QueueCfg)
    security: Security = Field(default_factory=Security)

    @field_validator("providers")
    @classmethod
    def _provider_names(cls, value: dict[str, Any]) -> dict[str, Any]:
        for name in value:
            if not _PROVIDER_NAME.match(name):
                raise ValueError(t("config.validation.provider_name", name=name))
        return value

    @field_validator("profiles")
    @classmethod
    def _keep_builtin_profiles(cls, value: dict[str, Profile]) -> dict[str, Profile]:
        return {**default_profiles(), **value}

    @field_validator("chiefs")
    @classmethod
    def _keep_builtin_chiefs(cls, value: dict[str, Chief]) -> dict[str, Chief]:
        return {**default_chiefs(), **value}

    @model_validator(mode="after")
    def _references_exist(self) -> Config:
        for field, name in (
            ("defaults.profile", self.defaults.profile),
            ("queue.default_profile", self.queue.default_profile),
        ):
            if name not in self.profiles:
                raise ValueError(t("config.validation.unknown_profile", field=field, name=name))
        if self.defaults.chief not in self.chiefs:
            raise ValueError(
                t(
                    "config.validation.unknown_chief",
                    field="defaults.chief",
                    name=self.defaults.chief,
                )
            )
        return self
