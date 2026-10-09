"""Contract tests for site_memory, reset_memory, clear_cache, strategies and config."""

import json

from tests.helpers import FakeStrategy, ladder, mcp_client, outcome
from webfetch2000.config import load_settings

URL = "http://fake.test/p"


async def fetch(client, url=URL, **kw):
    res = await client.call_tool("fetch", {"url": url, **kw})
    assert not res.isError, res.content
    return res.structuredContent


async def test_all_tools_registered(data_dir):
    async with mcp_client(data_dir=str(data_dir)) as client:
        names = {t.name for t in (await client.list_tools()).tools}
    assert {"fetch", "site_memory", "reset_memory", "clear_cache", "strategies", "config"} <= names


async def test_site_memory_reports_learning(data_dir):
    s = ladder(http=[outcome("x", status=403)])
    async with mcp_client(data_dir=str(data_dir), strategies=s, cache_ttl_s=1) as client:
        for _ in range(2):
            await fetch(client, cache="bypass")
        res = await client.call_tool("site_memory", {"domain": "fake.test"})
    assert not res.isError
    body = res.structuredContent
    assert body["domain"] == "fake.test"
    assert body["next_start_strategy"] == "browser"
    assert [r["strategy"] for r in body["ranking"]][0] == "browser"
    first = body["ranking"][0]
    assert {
        "strategy",
        "score",
        "successes",
        "failures",
        "mean_duration_ms",
        "last_attempt_at",
    } <= set(first)
    assert body["overrides"] == []


async def test_site_memory_normalizes_domain_and_unknown_site(data_dir):
    async with mcp_client(data_dir=str(data_dir)) as client:
        body = (
            await client.call_tool("site_memory", {"domain": "WWW.Unknown.test"})
        ).structuredContent
    assert body["domain"] == "unknown.test" and body["next_start_strategy"] == "http"
    assert all(r["observations"] == 0 for r in body["ranking"])


async def test_reset_memory_one_and_all(data_dir):
    async with mcp_client(data_dir=str(data_dir), strategies=ladder()) as client:
        await fetch(client, "http://a.test/x")
        await fetch(client, "http://b.test/x")
        one = (await client.call_tool("reset_memory", {"domain": "a.test"})).structuredContent
        assert one == {"cleared_domains": 1}
        allr = (await client.call_tool("reset_memory", {})).structuredContent
        assert allr["cleared_domains"] == 1
        snap = (await client.call_tool("site_memory", {"domain": "b.test"})).structuredContent
    assert all(r["observations"] == 0 for r in snap["ranking"])


async def test_clear_cache_by_url_domain_and_all(data_dir):
    s = ladder()
    async with mcp_client(data_dir=str(data_dir), strategies=s) as client:
        for u in ("http://a.test/1", "http://a.test/2", "http://b.test/1"):
            await fetch(client, u)
        assert (await fetch(client, "http://a.test/1"))["cache"] == "hit"
        r1 = (
            await client.call_tool("clear_cache", {"url": "http://a.test/1#frag"})
        ).structuredContent
        assert r1 == {"cleared_entries": 1}
        r2 = (await client.call_tool("clear_cache", {"domain": "www.a.test"})).structuredContent
        assert r2 == {"cleared_entries": 1}
        r3 = (await client.call_tool("clear_cache", {})).structuredContent
        assert r3 == {"cleared_entries": 1}
        assert (await fetch(client, "http://b.test/1"))["cache"] == "miss"


async def test_strategies_tool(data_dir):
    s = ladder()
    s["browser"] = FakeStrategy("browser", 2, available=False, reason="browser_not_installed")
    async with mcp_client(
        data_dir=str(data_dir), strategies=s, enabled_strategies=("http", "browser")
    ) as client:
        body = (await client.call_tool("strategies", {})).structuredContent
    by = {x["name"]: x for x in body["strategies"]}
    assert [x["name"] for x in body["strategies"]] == ["http", "browser", "stealth"]
    assert by["http"] == {"name": "http", "cost": 1, "available": True}
    assert (
        by["browser"]["available"] is False and by["browser"]["reason"] == "browser_not_installed"
    )
    assert by["stealth"]["available"] is False and by["stealth"]["reason"] == "disabled_by_settings"
    assert body["store"]["available"] is True and body["store"]["path"].endswith("webfetch.db")


async def test_config_tool_reports_values_and_sources(data_dir, tmp_path):
    cfg = tmp_path / "c.toml"
    cfg.write_text("timeout_s = 12\n")
    loaded = load_settings(
        env={"WEBFETCH_CACHE_TTL_S": "60", "WEBFETCH_DATA_DIR": str(data_dir)}, config_path=cfg
    )
    async with mcp_client(loaded.settings, loaded=loaded) as client:
        body = (await client.call_tool("config", {})).structuredContent
    assert body["config_file"] == str(cfg)
    assert body["settings"]["timeout_s"] == {"value": 12, "source": "file"}
    assert body["settings"]["cache_ttl_s"] == {"value": 60, "source": "env"}
    assert body["settings"]["retries"]["source"] == "default"
    assert body["settings"]["enabled_strategies"]["value"] == ["http", "browser", "stealth"]


async def test_management_tools_report_unavailable_store(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    async with mcp_client(data_dir=str(blocker / "sub"), strategies=ladder()) as client:
        res = await client.call_tool("site_memory", {"domain": "a.test"})
        assert res.isError and json.loads(res.content[0].text)["error"] == "store_unavailable"
        res = await client.call_tool("clear_cache", {})
        assert res.isError and json.loads(res.content[0].text)["error"] == "store_unavailable"
        body = (await client.call_tool("strategies", {})).structuredContent
        assert body["store"]["available"] is False and body["store"]["error"]
        fetched = await fetch(client, "http://c.test/x")
        assert any("memory and cache disabled" in w for w in fetched["warnings"])
