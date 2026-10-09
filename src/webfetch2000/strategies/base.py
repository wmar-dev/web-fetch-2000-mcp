"""Strategy protocol shared by the HTTP, Chromium and Camoufox fetchers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class StrategyRequest:
    url: str
    timeout_s: float
    max_bytes: int
    headed: bool = False
    negotiate_markdown: bool = True
    conditional_headers: dict[str, str] = field(default_factory=dict)


@dataclass
class FetchOutcome:
    status: int
    final_url: str
    headers: dict[str, str]  # lower-cased keys
    body: bytes
    content_type: str
    body_truncated: bool = False
    duration_ms: int = 0
    waited_ms: float = 0.0
    total_bytes: int | None = None


class StrategyError(Exception):
    """A transport-level failure (no usable HTTP response)."""

    def __init__(self, reason: str, message: str = "", retriable: bool = False) -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.retriable = retriable


class Strategy(ABC):
    name: str
    cost: int

    @abstractmethod
    async def available(self) -> tuple[bool, str | None]:
        """Return (usable, reason-if-not)."""

    @abstractmethod
    async def fetch(self, req: StrategyRequest) -> FetchOutcome: ...

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None
