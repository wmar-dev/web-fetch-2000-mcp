"""Cache wired into the router (US3)."""

import asyncio
import time

import pytest

from tests.helpers import CHALLENGE, ladder, make_settings, outcome
from webfetch2000.cache import Cache
from webfetch2000.models import FetchError, FetchRequest
from webfetch2000.router import Router
from webfetch2000.store import Store
from webfetch2000.strategies.http import HttpStrategy

URL = "http://fake.test/page"


def build(data_dir, strategies, **kw):
    settings = make_settings(**kw)
    cache = Cache(Store.open(data_dir / "c.db"), settings)
    return Router(settings, strategies, cache=cache), cache


async def test_repeat_request_is_served_from_cache_without_network(data_dir):
    s = ladder()
    r, _ = build(data_dir, s)
    first = await r.fetch(FetchRequest(url=URL))
    assert first.cache == "miss"
    t0 = time.perf_counter()
    second = await r.fetch(FetchRequest(url=URL))
    elapsed = time.perf_counter() - t0
    assert second.cache == "hit" and len(s["http"].calls) == 1
    assert elapsed < 0.1  # SC-004
    assert second.content == first.content and second.strategy_used == first.strategy_used
    assert second.attempts == []


async def test_url_fragment_and_case_share_an_entry(data_dir):
    s = ladder()
    r, _ = build(data_dir, s)
    await r.fetch(FetchRequest(url="http://FAKE.test/page#a"))
    res = await r.fetch(FetchRequest(url="http://fake.test/page#b"))
    assert res.cache == "hit" and len(s["http"].calls) == 1


async def test_markdown_and_raw_share_one_entry(data_dir):
    s = ladder()
    r, _ = build(data_dir, s)
    await r.fetch(FetchRequest(url=URL))
    raw = await r.fetch(FetchRequest(url=URL, format="raw"))
    assert raw.cache == "hit" and raw.format == "raw" and "<article>" in raw.content
    assert len(s["http"].calls) == 1


async def test_refresh_refetches_and_updates(data_dir):
    s = ladder(
        http=[
            outcome("<html><body><p>" + "old " * 80 + "</p></body></html>"),
            outcome("<html><body><p>" + "new " * 80 + "</p></body></html>"),
        ]
    )
    r, _ = build(data_dir, s)
    assert "old" in (await r.fetch(FetchRequest(url=URL))).content
    res = await r.fetch(FetchRequest(url=URL, cache="refresh"))
    assert res.cache == "miss" and "new" in res.content and len(s["http"].calls) == 2
    again = await r.fetch(FetchRequest(url=URL))
    assert again.cache == "hit" and "new" in again.content


async def test_bypass_neither_reads_nor_writes(data_dir):
    s = ladder()
    r, _ = build(data_dir, s)
    res = await r.fetch(FetchRequest(url=URL, cache="bypass"))
    assert res.cache == "bypassed"
    res = await r.fetch(FetchRequest(url=URL))  # nothing was written
    assert res.cache == "miss" and len(s["http"].calls) == 2
    res = await r.fetch(FetchRequest(url=URL, cache="bypass"))  # existing entry is ignored
    assert res.cache == "bypassed" and len(s["http"].calls) == 3


async def test_negotiation_variants_cached_separately(data_dir):
    s = ladder()
    r, _ = build(data_dir, s)
    await r.fetch(FetchRequest(url=URL, negotiate_markdown=True))
    res = await r.fetch(FetchRequest(url=URL, negotiate_markdown=False))
    assert res.cache == "miss" and len(s["http"].calls) == 2


async def test_failures_and_block_pages_are_never_cached(data_dir):
    s = ladder(
        http=[outcome("x", status=403)],
        browser=[outcome(CHALLENGE)],
        stealth=[outcome("x", status=403)],
    )
    r, cache = build(data_dir, s)
    with pytest.raises(FetchError):
        await r.fetch(FetchRequest(url=URL))
    assert cache.total_bytes() == 0


async def test_no_store_responses_are_not_cached(data_dir):
    s = ladder(http=[outcome(headers={"Cache-Control": "no-store"})])
    r, _ = build(data_dir, s)
    await r.fetch(FetchRequest(url=URL))
    res = await r.fetch(FetchRequest(url=URL))
    assert res.cache == "miss" and len(s["http"].calls) == 2


async def test_expired_entry_is_refetched(data_dir):
    s = ladder(http=[outcome(headers={"Cache-Control": "max-age=1"})])
    r, _ = build(data_dir, s)
    await r.fetch(FetchRequest(url=URL))
    await asyncio.sleep(1.2)
    res = await r.fetch(FetchRequest(url=URL))
    assert res.cache == "miss" and len(s["http"].calls) == 2


async def test_stale_entry_is_revalidated_with_conditional_request(data_dir):
    seen = {}

    def second(req):
        seen.update(req.conditional_headers)
        return outcome("", status=304, headers={"etag": '"v1"'})

    s = ladder(
        http=[
            outcome(headers={"ETag": '"v1"', "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"}),
            second,
        ]
    )
    r, _ = build(data_dir, s, cache_ttl_s=0)
    first = await r.fetch(FetchRequest(url=URL))
    res = await r.fetch(FetchRequest(url=URL))
    assert res.cache == "revalidated"
    assert seen["If-None-Match"] == '"v1"' and "If-Modified-Since" in seen
    assert res.content == first.content and len(s["http"].calls) == 2
    assert not s["browser"].calls


async def test_changed_content_after_revalidation_replaces_entry(data_dir):
    new = "<html><body><p>" + "fresh " * 80 + "</p></body></html>"
    s = ladder(http=[outcome(headers={"ETag": '"v1"'}), outcome(new, headers={"ETag": '"v2"'})])
    r, _ = build(data_dir, s, cache_ttl_s=0)
    await r.fetch(FetchRequest(url=URL))
    res = await r.fetch(FetchRequest(url=URL))
    assert res.cache == "miss" and "fresh" in res.content and len(s["http"].calls) == 2


async def test_unavailable_store_disables_cache_with_warning(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    settings = make_settings()
    s = ladder()
    r = Router(settings, s, cache=Cache(Store.open(blocker / "c.db"), settings))
    res = await r.fetch(FetchRequest(url=URL))
    assert res.strategy_used == "http" and any("cache" in w for w in res.warnings)


async def test_end_to_end_against_local_site(data_dir, site):
    settings = make_settings()
    cache = Cache(Store.open(data_dir / "c.db"), settings)
    r = Router(settings, {"http": HttpStrategy(settings, None)}, cache=cache)
    a = await r.fetch(FetchRequest(url=site.url("/count")))
    b = await r.fetch(FetchRequest(url=site.url("/count")))
    assert (a.cache, b.cache) == ("miss", "hit") and site.count("/count") == 1
    assert "hit 1" in b.content
    await r.close()


async def test_etag_revalidation_against_local_site(data_dir, site):
    settings = make_settings(cache_ttl_s=0)
    cache = Cache(Store.open(data_dir / "c.db"), settings)
    r = Router(settings, {"http": HttpStrategy(settings, None)}, cache=cache)
    await r.fetch(FetchRequest(url=site.url("/etag")))
    res = await r.fetch(FetchRequest(url=site.url("/etag")))
    assert res.cache == "revalidated" and site.count("/etag") == 2
    assert site.hits[-1]["headers"].get("if-none-match") == '"v1"'
    await r.close()
