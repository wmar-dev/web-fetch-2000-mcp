"""Real Chromium via Playwright (requires `playwright install chromium`)."""

import asyncio

import pytest

from tests.helpers import make_settings
from webfetch2000.models import FetchError
from webfetch2000.strategies.base import StrategyError, StrategyRequest
from webfetch2000.strategies.browser import BrowserStrategy

pytestmark = pytest.mark.browser


def sreq(url, **kw):
    return StrategyRequest(url=url, timeout_s=20, max_bytes=10_000_000, **kw)


@pytest.fixture
async def browser():
    made = []

    def make(**settings):
        s = BrowserStrategy(make_settings(**settings), None)
        made.append(s)
        return s

    yield make
    for s in made:
        await s.close()


async def test_available(browser):
    ok, reason = await browser().available()
    assert ok, reason


async def test_renders_javascript(browser, site):
    out = await browser().fetch(sreq(site.url("/js")))
    assert out.status == 200
    assert b"Rendered Heading" in out.body
    assert out.final_url == site.url("/js")


async def test_blocks_images_by_default(browser, site):
    await browser().fetch(sreq(site.url("/with-image")))
    assert site.count("/image") == 0


async def test_image_blocking_configurable(browser, site):
    await browser(block_resources=()).fetch(sreq(site.url("/with-image")))
    assert site.count("/image") >= 1


async def test_private_address_blocked_by_interception(browser, site):
    s = browser(allow_private_addresses=False)
    with pytest.raises(FetchError) as e:
        await s.fetch(sreq(site.url("/js")))
    assert e.value.code == "blocked_address"
    assert site.count("/js") == 0


async def test_pages_and_contexts_closed_after_use(browser, site):
    s = browser()
    await s.fetch(sreq(site.url("/js")))
    assert s.open_pages == 0
    with pytest.raises(StrategyError):
        await s.fetch(sreq("http://127.0.0.1:9/"))
    assert s.open_pages == 0


async def test_non_html_main_response(browser, site):
    out = await browser().fetch(sreq(site.url("/json")))
    assert out.content_type.startswith("application/json") and b'"a"' in out.body


async def test_idle_browser_is_shut_down(browser, site):
    s = browser(browser_idle_shutdown_s=1)
    await s.fetch(sreq(site.url("/js")))
    assert s.browser_count == 1
    await asyncio.sleep(7)
    assert s.browser_count == 0


async def test_concurrent_pages_bounded(browser, site):
    s = browser(browser_pages=2)
    await s.fetch(sreq(site.url("/js")))  # warm up: probe + launch
    tasks = [asyncio.create_task(s.fetch(sreq(site.url("/slow?s=1")))) for _ in range(4)]
    peak = 0
    while not all(t.done() for t in tasks):
        peak = max(peak, s.open_pages)
        await asyncio.sleep(0.05)
    await asyncio.gather(*tasks)
    assert peak == 2
