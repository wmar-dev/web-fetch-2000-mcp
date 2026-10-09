"""Test doubles and helpers shared by integration tests."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from tests.conftest import CHALLENGE_HTML, LOREM, STATIC_HTML
from webfetch2000.config import Settings
from webfetch2000.strategies.base import FetchOutcome, Strategy, StrategyError, StrategyRequest


def make_settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "allow_private_addresses": True,
        "retry_backoff_s": 0,
        "domain_rate_per_s": 0,
        "domain_concurrency": 0,
    }
    base.update(kw)
    return Settings(**base)


def outcome(
    body: str | bytes = STATIC_HTML,
    status: int = 200,
    content_type: str = "text/html; charset=utf-8",
    headers: dict[str, str] | None = None,
    url: str = "http://fake.test/page",
    **kw: Any,
) -> FetchOutcome:
    data = body.encode() if isinstance(body, str) else body
    h = {"content-type": content_type}
    h.update({k.lower(): v for k, v in (headers or {}).items()})
    return FetchOutcome(
        status=status, final_url=url, headers=h, body=data, content_type=content_type, **kw
    )


GOOD = STATIC_HTML
CHALLENGE = CHALLENGE_HTML
EMPTY = "<html><body></body></html>"
LONG_TEXT = LOREM


class FakeStrategy(Strategy):
    """Scripted strategy: each call consumes the next response (the last one repeats)."""

    def __init__(
        self,
        name: str,
        cost: int,
        *responses: FetchOutcome | Exception | Callable[[StrategyRequest], FetchOutcome],
        available: bool = True,
        reason: str | None = "not installed",
    ) -> None:
        self.name = name
        self.cost = cost
        self.responses = list(responses) or [outcome()]
        self._available = available
        self._reason = reason
        self.calls: list[StrategyRequest] = []
        self.closed = False

    async def available(self) -> tuple[bool, str | None]:
        return (True, None) if self._available else (False, self._reason)

    async def fetch(self, req: StrategyRequest) -> FetchOutcome:
        self.calls.append(req)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        r = self.responses[idx]
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(req)
        return r

    async def close(self) -> None:
        self.closed = True


@asynccontextmanager
async def mcp_client(settings: Settings | None = None, strategies=None, loaded=None, **kw: Any):
    """An in-memory MCP client session connected to a freshly built server."""
    from mcp.shared.memory import create_connected_server_and_client_session

    from webfetch2000.server import create_server

    server = create_server(settings or make_settings(**kw), strategies=strategies, loaded=loaded)
    async with create_connected_server_and_client_session(server._mcp_server) as client:
        yield client


def ladder(
    http: list | None = None, browser: list | None = None, stealth: list | None = None, **kw: Any
) -> dict[str, FakeStrategy]:
    return {
        "http": FakeStrategy("http", 1, *(http or [outcome()]), **kw),
        "browser": FakeStrategy("browser", 2, *(browser or [outcome()])),
        "stealth": FakeStrategy("stealth", 3, *(stealth or [outcome()])),
    }


__all__ = [
    "CHALLENGE",
    "EMPTY",
    "GOOD",
    "LONG_TEXT",
    "FakeStrategy",
    "StrategyError",
    "ladder",
    "make_settings",
    "mcp_client",
    "outcome",
]
