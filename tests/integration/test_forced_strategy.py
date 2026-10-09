"""Forcing a strategy, disabling fallback, and unavailable forced strategies (FR-011, FR-029)."""

import pytest

from tests.helpers import FakeStrategy, ladder, make_settings, outcome
from webfetch2000.models import FetchError, FetchRequest
from webfetch2000.router import Router

URL = "http://fake.test/p"


def router(strategies, **kw):
    return Router(make_settings(**kw), strategies)


async def test_forced_strategy_goes_first_and_alone_without_fallback():
    s = ladder()
    res = await router(s).fetch(FetchRequest(url=URL, strategy="browser", fallback=False))
    assert res.strategy_used == "browser"
    assert not s["http"].calls and not s["stealth"].calls


async def test_forced_failure_without_fallback_stops():
    s = ladder(browser=[outcome("x", status=403)])
    with pytest.raises(FetchError) as e:
        await router(s).fetch(FetchRequest(url=URL, strategy="browser", fallback=False))
    assert e.value.code == "all_strategies_failed"
    assert [a.strategy for a in e.value.attempts] == ["browser"]
    assert not s["stealth"].calls and not s["http"].calls


async def test_forced_failure_with_fallback_escalates_only_upward():
    s = ladder(browser=[outcome("x", status=403)])
    res = await router(s).fetch(FetchRequest(url=URL, strategy="browser", fallback=True))
    assert res.strategy_used == "stealth"
    assert [a.strategy for a in res.attempts] == ["browser", "stealth"]
    assert not s["http"].calls


async def test_forced_http_with_fallback_walks_the_ladder():
    s = ladder(http=[outcome("x", status=403)], browser=[outcome("x", status=403)])
    res = await router(s).fetch(FetchRequest(url=URL, strategy="http", fallback=True))
    assert [a.strategy for a in res.attempts] == ["http", "browser", "stealth"]


async def test_forced_unavailable_strategy_errors_and_does_not_substitute():
    s = ladder()
    s["stealth"] = FakeStrategy("stealth", 3, available=False, reason="camoufox_not_installed")
    with pytest.raises(FetchError) as e:
        await router(s).fetch(FetchRequest(url=URL, strategy="stealth", fallback=True))
    assert e.value.code == "strategy_unavailable"
    assert "camoufox_not_installed" in e.value.message and "stealth" in e.value.message
    assert not s["http"].calls and not s["browser"].calls  # FR-029


async def test_forced_disabled_strategy_errors():
    s = ladder()
    with pytest.raises(FetchError) as e:
        await router(s, enabled_strategies=("http",)).fetch(
            FetchRequest(url=URL, strategy="stealth")
        )
    assert e.value.code == "strategy_unavailable" and "disabled" in e.value.message
    assert not s["http"].calls


async def test_auto_is_unaffected_by_fallback_flag():
    s = ladder(http=[outcome("x", status=403)])
    res = await router(s).fetch(FetchRequest(url=URL, strategy="auto", fallback=False))
    assert res.strategy_used == "http" or res.strategy_used == "browser"


async def test_forced_strategy_still_enforces_url_safety():
    s = ladder()
    with pytest.raises(FetchError) as e:
        await router(s, allow_private_addresses=False).fetch(
            FetchRequest(url="http://127.0.0.1/", strategy="browser")
        )
    assert e.value.code == "blocked_address" and not s["browser"].calls


async def test_headed_flag_reaches_strategies():
    s = ladder()
    await router(s).fetch(FetchRequest(url=URL, strategy="browser", headed=True))
    assert s["browser"].calls[0].headed is True
    s = ladder()
    await router(s).fetch(FetchRequest(url=URL, strategy="browser"))
    assert s["browser"].calls[0].headed is False


async def test_per_call_negotiate_and_timeout_reach_strategies():
    s = ladder()
    await router(s).fetch(FetchRequest(url=URL, negotiate_markdown=False, timeout_s=7))
    call = s["http"].calls[0]
    assert call.negotiate_markdown is False and call.timeout_s == 7
