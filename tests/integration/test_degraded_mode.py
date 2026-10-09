"""Missing browsers or an unusable store must degrade, not crash (FR-015, FR-016)."""

from tests.helpers import FakeStrategy, ladder, make_settings
from webfetch2000.models import FetchRequest
from webfetch2000.router import Router
from webfetch2000.strategies.base import StrategyError


async def test_browsers_missing_http_still_works_and_warns():
    s = ladder()
    s["browser"] = FakeStrategy("browser", 2, available=False, reason="browser_not_installed")
    s["stealth"] = FakeStrategy("stealth", 3, available=False, reason="camoufox_not_installed")
    res = await Router(make_settings(), s).fetch(FetchRequest(url="http://fake.test/p"))
    assert res.strategy_used == "http"


async def test_unavailable_listed_in_warnings_when_needed():
    from tests.helpers import outcome

    s = ladder(http=[outcome("x", status=403)])
    s["browser"] = FakeStrategy("browser", 2, available=False, reason="browser_not_installed")
    s["stealth"] = FakeStrategy("stealth", 3, available=False, reason="camoufox_not_installed")
    import pytest

    from webfetch2000.models import FetchError

    with pytest.raises(FetchError) as e:
        await Router(make_settings(), s).fetch(FetchRequest(url="http://fake.test/p"))
    reasons = {a.strategy: a.reason for a in e.value.attempts}
    assert reasons["browser"] == "browser_not_installed"
    assert reasons["stealth"] == "camoufox_not_installed"


async def test_startup_warnings_are_included():
    r = Router(make_settings(), ladder(), startup_warnings=["memory and cache disabled: boom"])
    res = await r.fetch(FetchRequest(url="http://fake.test/p"))
    assert "memory and cache disabled: boom" in res.warnings


async def test_strategy_crash_is_a_failed_attempt_not_a_server_crash():
    s = ladder(http=[RuntimeError("kaboom")])
    res = await Router(make_settings(), s).fetch(FetchRequest(url="http://fake.test/p"))
    assert res.strategy_used == "browser"
    assert res.attempts[0].outcome == "failed" and "kaboom" in (res.attempts[0].reason or "")


def test_strategy_error_fields():
    e = StrategyError("timeout", "took too long", retriable=False)
    assert e.reason == "timeout" and not e.retriable
