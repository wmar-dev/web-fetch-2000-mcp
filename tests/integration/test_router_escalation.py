"""Router escalation with scripted strategies (US1)."""

import pytest

from tests.helpers import (
    CHALLENGE,
    EMPTY,
    FakeStrategy,
    StrategyError,
    ladder,
    make_settings,
    outcome,
)
from webfetch2000.models import FetchError, FetchRequest
from webfetch2000.router import Router


def router(strategies, **settings):
    return Router(make_settings(**settings), strategies)


async def test_cheapest_first_and_browser_never_used_for_static():
    s = ladder()
    res = await router(s).fetch(FetchRequest(url="http://fake.test/page"))
    assert res.strategy_used == "http"
    assert [a.outcome for a in res.attempts] == ["success"]
    assert len(s["http"].calls) == 1
    assert not s["browser"].calls and not s["stealth"].calls  # SC-005
    assert "Static Heading" in res.content and res.format == "markdown"
    assert res.markdown_source == "converted" and res.cache == "miss"


async def test_escalates_on_http_error_status():
    s = ladder(http=[outcome("<html>no</html>", status=403)])
    res = await router(s).fetch(FetchRequest(url="http://fake.test/page"))
    assert res.strategy_used == "browser"
    assert [(a.strategy, a.outcome, a.reason) for a in res.attempts] == [
        ("http", "failed", "http_403"),
        ("browser", "success", None),
    ]


async def test_escalates_on_200_challenge_page():
    s = ladder(http=[outcome(CHALLENGE)], browser=[outcome(CHALLENGE)])
    res = await router(s).fetch(FetchRequest(url="http://fake.test/page"))
    assert res.strategy_used == "stealth"
    assert [a.reason for a in res.attempts[:2]] == ["challenge_detected", "challenge_detected"]


async def test_escalates_on_empty_js_shell():
    s = ladder(http=[outcome(EMPTY)])
    res = await router(s).fetch(FetchRequest(url="http://fake.test/page"))
    assert res.strategy_used == "browser"
    assert res.attempts[0].reason in {"empty_content", "js_required"}


async def test_all_fail_error_lists_every_strategy_and_reason():
    s = ladder(
        http=[outcome("x", status=403)],
        browser=[outcome(CHALLENGE)],
        stealth=[StrategyError("timeout")],
    )
    with pytest.raises(FetchError) as e:
        await router(s).fetch(FetchRequest(url="http://fake.test/page"))
    err = e.value
    assert err.code == "all_strategies_failed"
    assert [(a.strategy, a.outcome, a.reason) for a in err.attempts] == [
        ("http", "failed", "http_403"),
        ("browser", "failed", "challenge_detected"),
        ("stealth", "failed", "timeout"),
    ]
    d = err.to_dict()
    assert d["error"] == "all_strategies_failed" and len(d["attempts"]) == 3  # SC-007


async def test_unavailable_strategy_is_skipped_and_reported():
    s = ladder(http=[outcome("x", status=403)])
    s["browser"] = FakeStrategy("browser", 2, available=False, reason="browser_not_installed")
    res = await router(s).fetch(FetchRequest(url="http://fake.test/page"))
    assert res.strategy_used == "stealth"
    assert ("browser", "unavailable", "browser_not_installed") in [
        (a.strategy, a.outcome, a.reason) for a in res.attempts
    ]
    assert any("browser" in w for w in res.warnings)


async def test_disabled_strategy_not_used():
    s = ladder(http=[outcome("x", status=403)])
    res = await router(s, enabled_strategies=("http", "stealth")).fetch(
        FetchRequest(url="http://fake.test/page")
    )
    assert res.strategy_used == "stealth" and not s["browser"].calls


async def test_retriable_error_is_retried_with_bound():
    s = ladder(http=[StrategyError("connect_error", retriable=True), outcome()])
    res = await router(s, retries=2).fetch(FetchRequest(url="http://fake.test/page"))
    assert res.strategy_used == "http" and len(s["http"].calls) == 2

    s = ladder(http=[StrategyError("connect_error", retriable=True)])
    res = await router(s, retries=2).fetch(FetchRequest(url="http://fake.test/page"))
    assert len(s["http"].calls) == 3 and res.strategy_used == "browser"


async def test_non_retriable_error_not_retried():
    s = ladder(http=[StrategyError("timeout")])
    await router(s, retries=2).fetch(FetchRequest(url="http://fake.test/page"))
    assert len(s["http"].calls) == 1


async def test_blocked_address_from_strategy_is_terminal():
    s = ladder(http=[FetchError("blocked_address", "redirect to private address")])
    with pytest.raises(FetchError) as e:
        await router(s).fetch(FetchRequest(url="http://fake.test/page"))
    assert e.value.code == "blocked_address" and not s["browser"].calls


async def test_invalid_urls_rejected_before_any_fetch():
    s = ladder()
    r = router(s, allow_private_addresses=False)
    for url, code in [
        ("ftp://x.test/", "unsupported_scheme"),
        ("http://127.0.0.1/", "blocked_address"),
        ("nonsense", "invalid_url"),
    ]:
        with pytest.raises(FetchError) as e:
            await r.fetch(FetchRequest(url=url))
        assert e.value.code == code
    assert not s["http"].calls


async def test_non_html_types_converted():
    s = ladder(http=[outcome('{"a": 1}', content_type="application/json")])
    res = await router(s).fetch(FetchRequest(url="http://fake.test/data"))
    assert res.content.startswith("```json") and res.strategy_used == "http"


async def test_binary_returns_metadata_only():
    s = ladder(http=[outcome(b"\x89PNG....", content_type="image/png")])
    res = await router(s).fetch(FetchRequest(url="http://fake.test/i.png"))
    assert res.content == "" and res.size_bytes == 8 and res.content_type == "image/png"


async def test_close_closes_strategies():
    s = ladder()
    r = router(s)
    await r.close()
    assert all(x.closed for x in s.values())
