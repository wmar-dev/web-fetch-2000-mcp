"""clear_cache and strategies tools."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from pydantic import Field

from .models import FetchError
from .results import error_result, ok_result, store_unavailable
from .safety import validate_url
from .store import StoreUnavailable
from .tools_memory import normalize_domain


def register(mcp: FastMCP, holder: Any) -> None:
    @mcp.tool()
    async def clear_cache(
        url: Annotated[str | None, Field(description="Clear entries for this URL")] = None,
        domain: Annotated[str | None, Field(description="Clear entries for this domain")] = None,
    ) -> CallToolResult:
        """Remove cached fetch results (one URL, one domain, or everything)."""
        app = holder.get()
        if app.cache is None:
            return store_unavailable(app.store.error)
        try:
            norm_url = validate_url(url).url if url else None
        except FetchError as e:
            return error_result(e)
        try:
            n = await asyncio.to_thread(
                app.cache.clear, norm_url, normalize_domain(domain) if domain else None
            )
        except (StoreUnavailable, sqlite3.Error) as e:
            return store_unavailable(str(e))
        return ok_result({"cleared_entries": n})

    @mcp.tool()
    async def strategies() -> CallToolResult:
        """List fetch strategies in cost order, whether each is available, and store status."""
        app = holder.get()
        status = await app.router.strategy_status()
        store: dict[str, Any] = {"available": app.store.available}
        if app.store.available:
            store["path"] = str(app.store.path)
        else:
            store["error"] = app.store.error
        return ok_result({"strategies": status, "store": store})
