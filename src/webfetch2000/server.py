"""MCP server: tool definitions and application wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated, Literal

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from pydantic import Field

from .cache import Cache
from .config import LoadedSettings, Settings
from .logging import get_logger
from .memory import Memory
from .models import FetchError, FetchRequest
from .ratelimit import DomainLimiter
from .results import error_result, ok_result
from .router import Router
from .store import Store
from .strategies.base import Strategy
from .strategies.browser import BrowserStrategy
from .strategies.http import HttpStrategy
from .strategies.stealth import StealthStrategy
from .tools_config import register_management_tools

log = get_logger("server")

SERVER_NAME = "web-fetch-2000"
DB_FILENAME = "webfetch.db"


@dataclass
class AppContext:
    settings: Settings
    loaded: LoadedSettings
    store: Store
    limiter: DomainLimiter
    router: Router
    memory: Memory | None = None
    cache: Cache | None = None
    warnings: list[str] = field(default_factory=list)

    async def close(self) -> None:
        await self.router.close()


def build_app(
    settings: Settings,
    loaded: LoadedSettings | None = None,
    strategies: Mapping[str, Strategy] | None = None,
) -> AppContext:
    warnings: list[str] = []
    store = Store.open(settings.resolved_data_dir() / DB_FILENAME)
    if not store.available:
        warnings.append(f"memory and cache disabled: {store.error}")
        log.warning("store unavailable", extra={"error": store.error})
    limiter = DomainLimiter(
        settings.domain_concurrency, settings.domain_rate_per_s, settings.domain_burst
    )
    if strategies is None:
        strategies = {
            "http": HttpStrategy(settings, limiter),
            "browser": BrowserStrategy(settings, limiter),
            "stealth": StealthStrategy(settings, limiter),
        }
    memory = Memory(store, settings) if store.available else None
    cache = Cache(store, settings) if store.available else None
    router = Router(
        settings, strategies, limiter=limiter, memory=memory, cache=cache, startup_warnings=warnings
    )
    loaded = loaded or LoadedSettings(settings, {k: "default" for k in Settings.model_fields})
    return AppContext(settings, loaded, store, limiter, router, memory, cache, warnings)


class AppHolder:
    app: AppContext | None = None

    def get(self) -> AppContext:
        if self.app is None:
            raise RuntimeError("server is not running")
        return self.app


def create_server(
    settings: Settings,
    *,
    loaded: LoadedSettings | None = None,
    strategies: Mapping[str, Strategy] | None = None,
) -> FastMCP:
    holder = AppHolder()

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[AppHolder]:
        holder.app = build_app(settings, loaded, strategies)
        try:
            yield holder
        finally:
            app, holder.app = holder.app, None
            with anyio.CancelScope(shield=True):
                await app.close()

    mcp = FastMCP(SERVER_NAME, lifespan=lifespan)
    mcp._holder = holder  # type: ignore[attr-defined]

    @mcp.tool()
    async def fetch(
        url: Annotated[str, Field(description="http(s) URL to fetch")],
        format: Annotated[
            Literal["markdown", "raw"],
            Field(description="markdown (default, best for assistants) or raw original data"),
        ] = "markdown",
        max_chars: Annotated[
            int, Field(ge=1, le=2_000_000, description="Max characters of markdown returned")
        ] = 50_000,
        strategy: Annotated[
            Literal["auto", "http", "browser", "stealth"],
            Field(description="auto picks the best known strategy and escalates on failure"),
        ] = "auto",
        fallback: Annotated[
            bool, Field(description="Escalate to heavier strategies when one fails")
        ] = True,
        cache: Annotated[
            Literal["use", "refresh", "bypass"],
            Field(description="use the cache, refresh it, or bypass it entirely"),
        ] = "use",
        timeout_s: Annotated[
            int | None, Field(ge=1, le=120, description="Per-strategy timeout in seconds")
        ] = None,
        headed: Annotated[
            bool, Field(description="Show the browser window (debugging; browser strategies)")
        ] = False,
        negotiate_markdown: Annotated[
            bool | None,
            Field(description="Override the negotiate_markdown setting for this call"),
        ] = None,
    ) -> CallToolResult:
        """Fetch a web page and return it as markdown (or raw data).

        Tries the cheapest strategy first (plain HTTP), then a JavaScript-rendering browser,
        then a stealth browser, and remembers what works per site. The result reports the
        strategy used, every attempt, cache status and any warnings.
        """
        req = FetchRequest(
            url=url,
            format=format,
            max_chars=max_chars,
            strategy=strategy,
            fallback=fallback,
            cache=cache,
            timeout_s=timeout_s,
            headed=headed,
            negotiate_markdown=negotiate_markdown,
        )
        try:
            result = await holder.get().router.fetch(req)
        except FetchError as e:
            return error_result(e)
        return ok_result(result.model_dump(mode="json"))

    register_management_tools(mcp, holder)
    return mcp
