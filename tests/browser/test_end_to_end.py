"""Full stack with real strategies: escalation, stealth, memory, cache (quickstart 1-6)."""

import pytest

from tests.helpers import make_settings, mcp_client

pytestmark = pytest.mark.browser


async def call(client, url, **kw):
    res = await client.call_tool("fetch", {"url": url, **kw})
    assert not res.isError, res.content
    return res.structuredContent


async def test_static_js_and_protected_pages(data_dir, site):
    settings = make_settings(data_dir=str(data_dir), timeout_s=60)
    async with mcp_client(settings) as client:
        static = await call(client, site.url("/static"))
        assert static["strategy_used"] == "http" and "Static Heading" in static["content"]

        js = await call(client, site.url("/js"))
        assert js["strategy_used"] == "browser" and "Rendered Heading" in js["content"]
        assert [a["strategy"] for a in js["attempts"]] == ["http", "browser"]
        assert js["attempts"][0]["reason"] in {"empty_content", "js_required"}

        protected = await call(client, site.url("/firefox-only"))
        assert protected["strategy_used"] == "stealth"
        assert [a["strategy"] for a in protected["attempts"]] == ["http", "browser", "stealth"]


async def test_memory_skips_known_failures_and_cache_hits(data_dir, site):
    # no random re-tests: this test asserts exactly which strategies are attempted
    settings = make_settings(data_dir=str(data_dir), timeout_s=60, reprobe_probability=0)
    url = site.url("/firefox-only")
    async with mcp_client(settings) as client:
        for _ in range(2):  # learning visits
            r = await call(client, url, cache="bypass")
            assert r["strategy_used"] == "stealth"
        before = site.count("/firefox-only")
        r = await call(client, url, cache="bypass")
        assert [a["strategy"] for a in r["attempts"]] == ["stealth"]  # no wasted attempts
        assert site.count("/firefox-only") == before + 1
        snap = (await client.call_tool("site_memory", {"domain": "127.0.0.1"})).structuredContent
        assert snap["next_start_strategy"] == "stealth"

        again = await call(client, url)
        again2 = await call(client, url)
        assert again2["cache"] == "hit" and again["strategy_used"] == "stealth"


async def test_forced_strategy_through_the_tool(data_dir, site):
    settings = make_settings(data_dir=str(data_dir), timeout_s=60)
    async with mcp_client(settings) as client:
        r = await call(client, site.url("/js"), strategy="browser", fallback=False)
        assert r["strategy_used"] == "browser" and [a["strategy"] for a in r["attempts"]] == [
            "browser"
        ]
        res = await client.call_tool(
            "fetch", {"url": site.url("/forbidden"), "strategy": "browser", "fallback": False}
        )
        assert res.isError
