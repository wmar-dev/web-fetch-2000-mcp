"""Identical in-flight requests share one fetch (FR-009)."""

import asyncio

import pytest

from tests.helpers import FakeStrategy, ladder, make_settings, outcome
from webfetch2000.models import FetchError, FetchRequest
from webfetch2000.router import Router
from webfetch2000.strategies.base import StrategyError


class SlowStrategy(FakeStrategy):
    def __init__(self, *a, delay=0.2, **kw):
        super().__init__(*a, **kw)
        self.delay = delay

    async def fetch(self, req):
        self.calls.append(req)
        await asyncio.sleep(self.delay)
        r = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(r, Exception):
            raise r
        return r


def slow_ladder(**kw):
    s = ladder()
    s["http"] = SlowStrategy("http", 1, outcome(), **kw)
    return s


async def test_identical_concurrent_requests_cause_one_fetch():
    s = slow_ladder()
    r = Router(make_settings(), s)
    results = await asyncio.gather(
        *[r.fetch(FetchRequest(url="http://fake.test/p")) for _ in range(5)]
    )
    assert len(s["http"].calls) == 1
    assert all("Static Heading" in x.content for x in results)
    assert len({x.content for x in results}) == 1


async def test_different_urls_do_not_coalesce():
    s = slow_ladder()
    r = Router(make_settings(), s)
    await asyncio.gather(
        r.fetch(FetchRequest(url="http://fake.test/a")),
        r.fetch(FetchRequest(url="http://fake.test/b")),
    )
    assert len(s["http"].calls) == 2


async def test_different_output_options_still_coalesce_one_fetch():
    s = slow_ladder()
    r = Router(make_settings(), s)
    md, raw = await asyncio.gather(
        r.fetch(FetchRequest(url="http://fake.test/p")),
        r.fetch(FetchRequest(url="http://fake.test/p", format="raw")),
    )
    assert len(s["http"].calls) == 1 and md.format == "markdown" and raw.format == "raw"


async def test_different_negotiation_does_not_coalesce():
    s = slow_ladder()
    r = Router(make_settings(), s)
    await asyncio.gather(
        r.fetch(FetchRequest(url="http://fake.test/p", negotiate_markdown=True)),
        r.fetch(FetchRequest(url="http://fake.test/p", negotiate_markdown=False)),
    )
    assert len(s["http"].calls) == 2


async def test_failure_propagates_to_all_followers_then_clears():
    s = ladder(
        http=[outcome("x", status=403)],
        browser=[outcome("x", status=403)],
        stealth=[StrategyError("timeout")],
    )
    s["http"] = SlowStrategy("http", 1, outcome("x", status=403))
    r = Router(make_settings(), s)
    outcomes = await asyncio.gather(
        *[r.fetch(FetchRequest(url="http://fake.test/p")) for _ in range(3)], return_exceptions=True
    )
    assert all(isinstance(o, FetchError) and o.code == "all_strategies_failed" for o in outcomes)
    assert len(s["http"].calls) == 1
    # the failed flight is gone: a new request tries again
    with pytest.raises(FetchError):
        await r.fetch(FetchRequest(url="http://fake.test/p"))
    assert len(s["http"].calls) == 2


async def test_cancelling_one_waiter_does_not_break_the_others():
    s = slow_ladder(delay=0.3)
    r = Router(make_settings(), s)
    t1 = asyncio.create_task(r.fetch(FetchRequest(url="http://fake.test/p")))
    t2 = asyncio.create_task(r.fetch(FetchRequest(url="http://fake.test/p")))
    await asyncio.sleep(0.05)
    t1.cancel()
    res = await t2
    assert "Static Heading" in res.content and len(s["http"].calls) == 1
    with pytest.raises(asyncio.CancelledError):
        await t1


async def test_sequential_requests_do_not_coalesce():
    s = slow_ladder(delay=0.01)
    r = Router(make_settings(), s)
    await r.fetch(FetchRequest(url="http://fake.test/p"))
    await r.fetch(FetchRequest(url="http://fake.test/p"))
    assert len(s["http"].calls) == 2  # no cache configured: nothing to serve the second from
