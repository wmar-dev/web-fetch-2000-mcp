"""Layered settings: defaults < TOML file < WEBFETCH_* environment < per-call arguments."""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

APP_NAME = "web-fetch-2000"
ENV_PREFIX = "WEBFETCH_"
STRATEGY_NAMES = ("http", "browser", "stealth")
RESOURCE_TYPES = ("image", "media", "font", "stylesheet", "script", "other")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


class ConfigError(Exception):
    """Invalid configuration; the message is safe to print to stderr."""


def _split_list(v: Any) -> Any:
    if isinstance(v, str):
        return tuple(p.strip() for p in v.split(",") if p.strip())
    if isinstance(v, list):
        return tuple(v)
    return v


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Limits
    timeout_s: int = Field(30, ge=1, le=120)
    max_response_bytes: int = Field(10_000_000, ge=1_000)
    max_redirects: int = Field(5, ge=0, le=20)
    retries: int = Field(2, ge=0, le=10)
    retry_backoff_s: float = Field(0.5, ge=0)

    # Concurrency
    http_concurrency: int = Field(20, ge=1)
    browser_pages: int = Field(2, ge=1)
    stealth_pages: int = Field(1, ge=1)
    browser_idle_shutdown_s: int = Field(60, ge=1)

    # Browsers
    browser_headless: bool = True
    stealth_headless: bool = True
    block_resources: tuple[str, ...] = ("image", "media", "font")
    no_sandbox: bool = False

    # Strategies
    enabled_strategies: tuple[str, ...] = STRATEGY_NAMES

    # Cache
    cache_ttl_s: int = Field(3600, ge=0)
    cache_max_mb: int = Field(200, ge=1)
    respect_cache_control: bool = True

    # Memory (advanced)
    half_life_days: float = Field(14, gt=0)
    reprobe_after_days: float = Field(7, gt=0)
    reprobe_probability: float = Field(0.05, ge=0, le=1)
    score_tolerance: float = Field(0.1, ge=0, le=1)
    min_observations: int = Field(2, ge=1)
    override_min_observations: int = Field(5, ge=1)
    max_prefixes_per_domain: int = Field(20, ge=1)

    # Rate limiting (0 disables a limit)
    domain_concurrency: int = Field(2, ge=0)
    domain_rate_per_s: float = Field(2.0, ge=0)
    domain_burst: int = Field(4, ge=0)
    max_retry_after_s: int = Field(30, ge=0)

    # Usability
    min_content_chars: int = Field(200, ge=0)
    extra_block_markers: tuple[str, ...] = ()

    # Identity / negotiation
    user_agent: str = DEFAULT_USER_AGENT
    extra_headers: dict[str, str] = Field(default_factory=dict)
    negotiate_markdown: bool = True

    # Safety
    allow_private_addresses: bool = False
    allow_domains: tuple[str, ...] = ()
    deny_domains: tuple[str, ...] = ()

    # Storage and logs
    data_dir: str | None = None
    log_level: str = "INFO"

    @field_validator(
        "enabled_strategies",
        "block_resources",
        "extra_block_markers",
        "allow_domains",
        "deny_domains",
        mode="before",
    )
    @classmethod
    def _lists(cls, v: Any) -> Any:
        return _split_list(v)

    @field_validator("extra_headers", mode="before")
    @classmethod
    def _headers(cls, v: Any) -> Any:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError as e:
                raise ValueError(f"must be a JSON object ({e.msg})") from e
        return v

    @field_validator("enabled_strategies")
    @classmethod
    def _strategies(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        bad = [s for s in v if s not in STRATEGY_NAMES]
        if bad or not v:
            raise ValueError(f"must be a non-empty subset of {list(STRATEGY_NAMES)}")
        return v

    @field_validator("block_resources")
    @classmethod
    def _resources(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        bad = [s for s in v if s not in RESOURCE_TYPES]
        if bad:
            raise ValueError(f"unknown resource types {bad}; allowed {list(RESOURCE_TYPES)}")
        return v

    @field_validator("log_level")
    @classmethod
    def _level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL")
        return v

    def with_overrides(self, **overrides: Any) -> Settings:
        """Return a validated copy with per-call overrides (None values are ignored)."""
        clean = {k: v for k, v in overrides.items() if v is not None}
        return Settings.model_validate({**self.model_dump(), **clean})

    def resolved_data_dir(self) -> Path:
        if self.data_dir:
            return Path(self.data_dir).expanduser()
        return Path(platformdirs.user_data_dir(APP_NAME))


@dataclass
class LoadedSettings:
    settings: Settings
    sources: dict[str, str] = field(default_factory=dict)
    config_file: Path | None = None


class _Auto:
    pass


AUTO = _Auto()


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME)) / "config.toml"


def load_settings(
    env: Mapping[str, str] | None = None,
    config_path: Path | None | _Auto = AUTO,
) -> LoadedSettings:
    env = os.environ if env is None else env
    file_values: dict[str, Any] = {}
    used_file: Path | None = None

    if isinstance(config_path, _Auto):
        explicit = env.get(f"{ENV_PREFIX}CONFIG")
        path: Path | None = Path(explicit).expanduser() if explicit else default_config_path()
        must_exist = bool(explicit)
    else:
        path, must_exist = config_path, True

    if path is not None and (path.exists() or must_exist):
        try:
            file_values = tomllib.loads(path.read_text())
            used_file = path
        except FileNotFoundError as e:
            raise ConfigError(f"config file not found: {path}") from e
        except (tomllib.TOMLDecodeError, OSError) as e:
            raise ConfigError(f"invalid config file {path}: {e}") from e

    fields = Settings.model_fields
    unknown = [k for k in file_values if k not in fields]
    if unknown:
        raise ConfigError(f"invalid config file {path}: unknown setting(s) {sorted(unknown)}")

    env_values: dict[str, str] = {}
    for name in fields:
        key = f"{ENV_PREFIX}{name.upper()}"
        if key in env:
            env_values[name] = env[key]

    merged = {**file_values, **env_values}
    try:
        settings = Settings.model_validate(merged)
    except ValidationError as e:
        problems = []
        for err in e.errors():
            name = str(err["loc"][0]) if err["loc"] else "?"
            origin = (
                f"{ENV_PREFIX}{name.upper()}" if name in env_values else f"{name} (config file)"
            )
            problems.append(f"{origin}: {err['msg']}")
        raise ConfigError("invalid configuration: " + "; ".join(problems)) from e

    sources = {
        name: "env" if name in env_values else "file" if name in file_values else "default"
        for name in fields
    }
    return LoadedSettings(settings=settings, sources=sources, config_file=used_file)
