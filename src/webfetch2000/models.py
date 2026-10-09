"""Request, result and error models shared by the router, strategies and MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

StrategyName = Literal["http", "browser", "stealth"]
ErrorCode = Literal[
    "invalid_url",
    "blocked_address",
    "unsupported_scheme",
    "all_strategies_failed",
    "strategy_unavailable",
    "timeout",
    "too_large",
    "rate_limited",
    "store_unavailable",
]
AttemptOutcome = Literal["success", "failed", "skipped", "unavailable", "deferred"]


class Attempt(BaseModel):
    strategy: str
    outcome: AttemptOutcome
    reason: str | None = None
    duration_ms: int = 0


class FetchError(Exception):
    """A structured, caller-visible failure (maps to an MCP error result)."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        attempts: list[Attempt] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.attempts = attempts or []
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.code, "message": self.message}
        if self.attempts:
            out["attempts"] = [a.model_dump() for a in self.attempts]
        out.update({k: v for k, v in self.extra.items() if v is not None})
        return out


class FetchRequest(BaseModel):
    url: str
    format: Literal["markdown", "raw"] = "markdown"
    max_chars: int = Field(default=50_000, ge=1, le=2_000_000)
    strategy: Literal["auto", "http", "browser", "stealth"] = "auto"
    fallback: bool = True
    cache: Literal["use", "refresh", "bypass"] = "use"
    timeout_s: int | None = Field(default=None, ge=1, le=120)
    headed: bool = False
    negotiate_markdown: bool | None = None


class FetchResult(BaseModel):
    url: str
    final_url: str
    status: int
    content_type: str
    format: Literal["markdown", "raw"]
    content: str
    content_encoding: Literal["utf-8", "base64"] = "utf-8"
    truncated: bool = False
    total_chars: int | None = None
    total_bytes: int | None = None
    size_bytes: int | None = None
    strategy_used: str
    attempts: list[Attempt] = Field(default_factory=list)
    cache: Literal["hit", "miss", "revalidated", "bypassed"] = "miss"
    markdown_source: Literal["origin", "converted"] | None = None
    origin_tokens: int | None = None
    content_signals: str | None = None
    duration_ms: int = 0
    waited_ms: int = 0
    warnings: list[str] = Field(default_factory=list)


@dataclass
class Fetched:
    """The strategy-independent result of one underlying fetch (cacheable)."""

    final_url: str
    status: int
    content_type: str
    markdown: str
    kind: str
    raw: bytes
    raw_truncated: bool
    total_bytes: int | None
    strategy_used: str
    attempts: list[Attempt]
    origin_tokens: int | None = None
    content_signals: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    cache_control: str | None = None
    waited_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def markdown_source(self) -> str | None:
        if self.kind == "binary":
            return None
        return "origin" if self.kind == "markdown" else "converted"
