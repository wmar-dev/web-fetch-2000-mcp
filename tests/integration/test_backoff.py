"""429/503 are back-off signals: wait, retry the same strategy, never escalate (FR-028)."""

import time

import pytest

from tests.helpers import ladder, make_settings, outcome
from webfetch2000.models import FetchError, FetchRequest
from webfetch2000.router import Router
from webfetch2000.strategies.http import HttpStrategy


async def test_429_waits_and_retries_same_strategy():
    s = ladder(http=[outcome("slow", status=429, headers={"Retry-After": "0.15"}), outcome()])
    t0 = time.monotonic()
    res = await Router(make_settings(), s).fetch(FetchRequest(url="http://fake.test/p"))
    assert time.monotonic() - t0 >= 0.14
    assert res.strategy_used == "http" and len(s["http"].calls) == 2
    assert not s["browser"].calls  # never escalated
    assert res.waited_ms >= 140
    assert [a.outcome for a in res.attempts] == ["deferred", "success"]
    assert res.attempts[0].reason == "http_429"


@pytest.mark.parametrize("status", [429, 503])
async def test_gives_up_with_rate_limited_error_and_does_not_escalate(status):
    s = ladder(http=[outcome("x", status=status, headers={"Retry-After": "0"})])
    with pytest.raises(FetchError) as e:
        await Router(make_settings(retries=2), s).fetch(FetchRequest(url="http://fake.test/p"))
    assert e.value.code == "rate_limited"
    assert len(s["http"].calls) == 3
    assert not s["browser"].calls and not s["stealth"].calls
    assert e.value.to_dict().get("retry_after_s") == 0


async def test_retry_after_capped_by_setting():
    s = ladder(http=[outcome("x", status=429, headers={"Retry-After": "3600"}), outcome()])
    t0 = time.monotonic()
    res = await Router(make_settings(max_retry_after_s=0), s).fetch(
        FetchRequest(url="http://fake.test/p")
    )
    assert time.monotonic() - t0 < 1 and res.strategy_used == "http"


async def test_without_retry_after_uses_backoff():
    s = ladder(http=[outcome("x", status=503), outcome()])
    res = await Router(make_settings(retry_backoff_s=0.05), s).fetch(
        FetchRequest(url="http://fake.test/p")
    )
    assert res.strategy_used == "http" and res.waited_ms >= 40


async def test_real_http_strategy_against_local_site(site):
    settings = make_settings()
    router = Router(settings, {"http": HttpStrategy(settings, None)})
    url = site.url("/ratelimited?fail=1&retry_after=0.2")
    res = await router.fetch(FetchRequest(url=url))
    assert res.strategy_used == "http" and site.count("/ratelimited") == 2
    await router.close()
