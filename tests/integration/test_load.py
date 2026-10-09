"""Load behaviour: per-domain limits, bounded memory, no leftover browsers (SC-006, SC-014)."""

import asyncio
import gc
import time

import pytest

from tests.helpers import make_settings
from webfetch2000.cache import Cache
from webfetch2000.models import FetchRequest
from webfetch2000.ratelimit import DomainLimiter
from webfetch2000.router import Router
from webfetch2000.store import Store
from webfetch2000.strategies.http import HttpStrategy

pytestmark = pytest.mark.slow


def rss_mb() -> float:
    import psutil

    return psutil.Process().memory_info().rss / 1024 / 1024


async def test_fifty_concurrent_requests_respect_domain_limits(site, data_dir):
    settings = make_settings(
        domain_concurrency=2, domain_rate_per_s=20, domain_burst=4, timeout_s=60
    )
    limiter = DomainLimiter(2, 20, 4)
    cache = Cache(Store.open(data_dir / "l.db"), settings)
    router = Router(
        settings, {"http": HttpStrategy(settings, limiter)}, limiter=limiter, cache=cache
    )
    gc.collect()
    baseline = rss_mb()
    urls = [site.url(f"/track?i={i}") for i in range(50)]
    t0 = time.monotonic()
    results = await asyncio.gather(*[router.fetch(FetchRequest(url=u)) for u in urls])
    elapsed = time.monotonic() - t0

    assert all(r.status == 200 for r in results)
    assert site.peak <= 2  # SC-014: never more than domain_concurrency in flight
    times = sorted(h["t"] for h in site.hits if h["path"] == "/track")
    assert len(times) == 50
    for i, t in enumerate(times):  # never more than rate + burst in any 1 s window
        in_window = sum(1 for x in times[i:] if x < t + 1.0)
        assert in_window <= 20 + 4 + 1
    assert elapsed >= (50 - 4) / 20 * 0.9  # the limiter really paced the requests

    await router.close()
    gc.collect()
    assert rss_mb() < 1024  # SC-006
    assert rss_mb() - baseline < 300


@pytest.mark.browser
async def test_browser_load_bounded_and_no_leftover_processes(site, data_dir):
    import psutil

    settings = make_settings(
        browser_pages=2,
        domain_concurrency=0,
        domain_rate_per_s=0,
        timeout_s=90,
        enabled_strategies=("http", "browser"),
    )
    limiter = DomainLimiter(0, 0, 0)
    from webfetch2000.strategies.browser import BrowserStrategy

    browser = BrowserStrategy(settings, limiter)
    router = Router(
        settings, {"http": HttpStrategy(settings, limiter), "browser": browser}, limiter=limiter
    )
    me = psutil.Process()
    # other tests may leave helper processes (e.g. multiprocessing's resource tracker) behind:
    # only processes started by this test count
    baseline = {c.pid for c in me.children(recursive=True)}

    def new_children():
        return [
            c
            for c in me.children(recursive=True)
            if c.pid not in baseline and c.is_running() and c.status() != psutil.STATUS_ZOMBIE
        ]

    tasks = [
        asyncio.create_task(router.fetch(FetchRequest(url=site.url(f"/js?i={i}"), cache="bypass")))
        for i in range(20)
    ]
    peak = 0
    while not all(t.done() for t in tasks):
        peak = max(peak, browser.open_pages)
        await asyncio.sleep(0.05)
    results = await asyncio.gather(*tasks)
    assert all(r.strategy_used == "browser" for r in results)
    assert peak <= 2
    assert sum(c.memory_info().rss for c in new_children()) / 1024 / 1024 < 1024

    await router.close()
    await asyncio.sleep(1)
    assert not new_children()
