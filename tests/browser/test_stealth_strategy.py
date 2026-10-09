"""Real Camoufox (requires `python -m camoufox fetch`)."""

import os

import pytest

from tests.helpers import make_settings
from webfetch2000.strategies.base import StrategyRequest
from webfetch2000.strategies.browser import BrowserStrategy
from webfetch2000.strategies.stealth import StealthStrategy

pytestmark = pytest.mark.browser


def sreq(url, **kw):
    return StrategyRequest(url=url, timeout_s=60, max_bytes=10_000_000, **kw)


@pytest.fixture
async def stealth():
    made = []

    def make(**settings):
        s = StealthStrategy(make_settings(**settings), None)
        made.append(s)
        return s

    yield make
    for s in made:
        await s.close()


async def test_available(stealth):
    ok, reason = await stealth().available()
    assert ok, reason


async def test_fetches_js_page(stealth, site):
    out = await stealth().fetch(sreq(site.url("/js")))
    assert out.status == 200 and b"Rendered Heading" in out.body


async def test_passes_where_chromium_is_rejected(stealth, site):
    chromium = BrowserStrategy(make_settings(), None)
    try:
        assert (await chromium.fetch(sreq(site.url("/firefox-only")))).status == 403
    finally:
        await chromium.close()
    out = await stealth().fetch(sreq(site.url("/firefox-only")))
    assert out.status == 200


async def test_cleanup_on_close(stealth, site):
    s = stealth()
    await s.fetch(sreq(site.url("/js")))
    assert s.browser_count == 1 and s.open_pages == 0
    await s.close()
    assert s.browser_count == 0


@pytest.mark.skipif(not os.environ.get("WEBFETCH_TEST_HEADED"), reason="opens a visible window")
async def test_headed_option(stealth, site):
    out = await stealth(stealth_headless=False).fetch(sreq(site.url("/js"), headed=True))
    assert out.status == 200
