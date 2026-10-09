"""site_memory and reset_memory tools."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from pydantic import Field

from .results import ok_result, store_unavailable
from .router import LADDER
from .store import StoreUnavailable


def normalize_domain(domain: str) -> str:
    d = domain.strip().lower().rstrip(".")
    return d[4:] if d.startswith("www.") else d


def register(mcp: FastMCP, holder: Any) -> None:
    @mcp.tool()
    async def site_memory(
        domain: Annotated[str, Field(description="Domain to inspect, e.g. example.com")],
        path: Annotated[str | None, Field(description="Optional path to see its section")] = None,
    ) -> CallToolResult:
        """Show which fetch strategy the server has learned works best for a site.

        Returns the ranking (best first), per-section overrides and the strategy the next
        fetch will start with.
        """
        app = holder.get()
        if app.memory is None:
            return store_unavailable(app.store.error)
        ladder = [n for n in LADDER if n in app.settings.enabled_strategies]
        try:
            snap = await asyncio.to_thread(
                app.memory.snapshot, normalize_domain(domain), path, ladder
            )
        except (StoreUnavailable, sqlite3.Error) as e:
            return store_unavailable(str(e))
        return ok_result(snap)

    @mcp.tool()
    async def reset_memory(
        domain: Annotated[
            str | None, Field(description="Domain to forget; omit to clear everything learned")
        ] = None,
    ) -> CallToolResult:
        """Forget learned strategy preferences for one domain, or for all domains."""
        app = holder.get()
        if app.memory is None:
            return store_unavailable(app.store.error)
        try:
            n = await asyncio.to_thread(
                app.memory.reset, normalize_domain(domain) if domain else None
            )
        except (StoreUnavailable, sqlite3.Error) as e:
            return store_unavailable(str(e))
        return ok_result({"cleared_domains": n})
