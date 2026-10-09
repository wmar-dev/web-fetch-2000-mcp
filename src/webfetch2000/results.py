"""MCP tool result helpers."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import CallToolResult, TextContent

from .models import FetchError


def error_result(err: FetchError) -> CallToolResult:
    return CallToolResult(
        isError=True, content=[TextContent(type="text", text=json.dumps(err.to_dict()))]
    )


def ok_result(data: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, default=str))],
        structuredContent=data,
    )


def store_unavailable(reason: str | None) -> CallToolResult:
    return error_result(
        FetchError("store_unavailable", f"memory and cache are unavailable: {reason or 'unknown'}")
    )
