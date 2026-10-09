"""config tool, plus registration of the management tool modules."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from . import tools_cache, tools_memory
from .results import ok_result


def _jsonable(v: Any) -> Any:
    if isinstance(v, tuple):
        return list(v)
    return v


def register(mcp: FastMCP, holder: Any) -> None:
    @mcp.tool()
    async def config() -> CallToolResult:
        """Show the effective settings and where each value came from (default, file or env)."""
        app = holder.get()
        values = app.settings.model_dump()
        settings = {
            name: {
                "value": _jsonable(values[name]),
                "source": app.loaded.sources.get(name, "default"),
            }
            for name in values
        }
        return ok_result(
            {
                "settings": settings,
                "config_file": str(app.loaded.config_file) if app.loaded.config_file else None,
            }
        )


def register_management_tools(mcp: FastMCP, holder: Any) -> None:
    tools_memory.register(mcp, holder)
    tools_cache.register(mcp, holder)
    register(mcp, holder)
