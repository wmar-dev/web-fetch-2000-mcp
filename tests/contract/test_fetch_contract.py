"""Contract tests for the `fetch` tool over a real in-memory MCP session."""

import json

import pytest

from tests.helpers import make_settings, mcp_client


async def test_fetch_tool_schema(data_dir):
    async with mcp_client(data_dir=str(data_dir)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
    assert "fetch" in tools
    schema = tools["fetch"].inputSchema
    assert schema["required"] == ["url"]
    props = schema["properties"]
    for name in (
        "url",
        "format",
        "max_chars",
        "strategy",
        "fallback",
        "cache",
        "timeout_s",
        "headed",
        "negotiate_markdown",
    ):
        assert name in props, name
    assert set(props["format"]["enum"]) == {"markdown", "raw"}
    assert set(props["strategy"]["enum"]) == {"auto", "http", "browser", "stealth"}
    assert set(props["cache"]["enum"]) == {"use", "refresh", "bypass"}
    assert props["max_chars"]["default"] == 50000
    t = props["timeout_s"]
    bounds = [t] + t.get("anyOf", [])
    assert any(b.get("maximum") == 120 and b.get("minimum") == 1 for b in bounds)
    assert tools["fetch"].description and "markdown" in tools["fetch"].description.lower()


async def test_success_shape(data_dir, site):
    async with mcp_client(data_dir=str(data_dir)) as client:
        res = await client.call_tool("fetch", {"url": site.url("/static")})
    assert not res.isError
    body = res.structuredContent
    for key in (
        "url",
        "final_url",
        "status",
        "content_type",
        "format",
        "content",
        "truncated",
        "strategy_used",
        "attempts",
        "cache",
        "duration_ms",
        "warnings",
    ):
        assert key in body, key
    assert body["status"] == 200 and body["strategy_used"] == "http"
    assert body["format"] == "markdown" and "Static Heading" in body["content"]
    assert body["attempts"][0] == {
        "strategy": "http",
        "outcome": "success",
        "reason": None,
        "duration_ms": body["attempts"][0]["duration_ms"],
    }
    assert json.loads(res.content[0].text)["status"] == 200


@pytest.mark.parametrize(
    "url,code",
    [
        ("ftp://example.com/x", "unsupported_scheme"),
        ("nonsense", "invalid_url"),
        ("http://169.254.169.254/", "blocked_address"),
    ],
)
async def test_error_shape(data_dir, url, code):
    settings = make_settings(data_dir=str(data_dir), allow_private_addresses=False)
    async with mcp_client(settings) as client:
        res = await client.call_tool("fetch", {"url": url})
    assert res.isError
    body = json.loads(res.content[0].text)
    assert body["error"] == code and body["message"]


async def test_all_strategies_failed_error_lists_attempts(data_dir, site):
    async with mcp_client(data_dir=str(data_dir), enabled_strategies=("http",)) as client:
        res = await client.call_tool("fetch", {"url": site.url("/forbidden")})
    assert res.isError
    body = json.loads(res.content[0].text)
    assert body["error"] == "all_strategies_failed"
    assert body["attempts"][0]["strategy"] == "http" and body["attempts"][0]["reason"] == "http_403"


async def test_argument_validation(data_dir):
    async with mcp_client(data_dir=str(data_dir)) as client:
        res = await client.call_tool("fetch", {"url": "http://x.test/", "max_chars": 0})
    assert res.isError
