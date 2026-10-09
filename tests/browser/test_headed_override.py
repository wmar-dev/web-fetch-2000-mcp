"""Per-call `headed` override (opens a visible window; gated by WEBFETCH_TEST_HEADED)."""

import os

import pytest

from tests.helpers import make_settings
from webfetch2000.strategies.base import StrategyRequest
from webfetch2000.strategies.browser import BrowserStrategy

pytestmark = pytest.mark.browser


def sreq(url, **kw):
    return StrategyRequest(url=url, timeout_s=30, max_bytes=10_000_000, **kw)


async def test_default_stays_headless(site):
    s = BrowserStrategy(make_settings(), None)
    try:
        await s.fetch(sreq(site.url("/js")))
        assert set(s._handles) == {True}
    finally:
        await s.close()


@pytest.mark.skipif(not os.environ.get("WEBFETCH_TEST_HEADED"), reason="opens a visible window")
async def test_headed_only_for_that_call(site):
    s = BrowserStrategy(make_settings(), None)
    try:
        out = await s.fetch(sreq(site.url("/js"), headed=True))
        assert out.status == 200 and False in s._handles
        await s.fetch(sreq(site.url("/js")))
        assert True in s._handles
    finally:
        await s.close()
