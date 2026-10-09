"""Memory wired into the router: learning, persistence across restarts, no deferred records."""

from tests.helpers import FakeStrategy, ladder, make_settings, outcome
from webfetch2000.memory import Memory
from webfetch2000.models import FetchRequest
from webfetch2000.router import Router
from webfetch2000.store import Store


def build(data_dir, strategies, **kw):
    settings = make_settings(**kw)
    store = Store.open(data_dir / "w.db")
    return Router(settings, strategies, memory=Memory(store, settings, rng=lambda: 0.99)), store


def blocked_http():
    return ladder(http=[outcome("nope", status=403)])


async def test_skips_failed_strategies_on_repeat_visits(data_dir):
    s = blocked_http()
    r, _ = build(data_dir, s)
    req = FetchRequest(url="http://fake.test/page")
    for _ in range(2):  # learning
        res = await r.fetch(req)
        assert res.strategy_used == "browser"
    calls_before = len(s["http"].calls)
    res = await r.fetch(req)
    assert res.strategy_used == "browser"
    assert len(s["http"].calls) == calls_before  # http no longer attempted (SC-002/003)
    assert [a.strategy for a in res.attempts] == ["browser"]


async def test_learning_survives_restart(data_dir):
    s = blocked_http()
    r, _ = build(data_dir, s)
    req = FetchRequest(url="http://fake.test/page")
    for _ in range(2):
        await r.fetch(req)
    await r.close()

    s2 = blocked_http()  # a brand-new process: new router, new memory, same store file
    r2, _ = build(data_dir, s2)
    res = await r2.fetch(req)
    assert [a.strategy for a in res.attempts] == ["browser"]  # SC-008
    assert not s2["http"].calls


async def test_falls_back_when_remembered_strategy_stops_working(data_dir):
    s = blocked_http()
    r, store = build(data_dir, s)
    req = FetchRequest(url="http://fake.test/page")
    for _ in range(3):
        await r.fetch(req)
    # the browser strategy now fails; stealth works
    s["browser"].responses = [outcome("x", status=403)]
    s["browser"].calls.clear()
    res = await r.fetch(req)
    assert res.strategy_used == "stealth"
    assert [a.strategy for a in res.attempts] == ["browser", "stealth"]
    with store.conn() as c:
        row = c.execute(
            "select failures from outcomes where domain='fake.test' and strategy='browser' and path_prefix=''"
        ).fetchone()
    assert row[0] > 0  # memory updated


async def test_deferred_outcomes_are_not_recorded(data_dir):
    s = ladder(http=[outcome("slow", status=429, headers={"Retry-After": "0"}), outcome()])
    r, store = build(data_dir, s)
    await r.fetch(FetchRequest(url="http://fake.test/p"))
    with store.conn() as c:
        rows = c.execute(
            "select successes, failures from outcomes where strategy='http' and path_prefix=''"
        ).fetchall()
    assert len(rows) == 1 and rows[0][0] > 0.99 and rows[0][1] == 0  # SC-015


async def test_unavailable_attempts_are_not_recorded(data_dir):
    s = ladder(http=[outcome("x", status=403)])
    s["browser"] = FakeStrategy("browser", 2, available=False)
    r, store = build(data_dir, s)
    await r.fetch(FetchRequest(url="http://fake.test/p"))
    with store.conn() as c:
        strategies = {x[0] for x in c.execute("select strategy from outcomes")}
    assert strategies == {"http", "stealth"}


async def test_memory_is_keyed_by_requested_domain_not_redirect_target(data_dir):
    s = ladder(http=[outcome(url="http://elsewhere.test/landing")])
    r, store = build(data_dir, s)
    await r.fetch(FetchRequest(url="http://short.test/abc"))
    with store.conn() as c:
        domains = {x[0] for x in c.execute("select domain from outcomes")}
    assert domains == {"short.test"}


async def test_unavailable_store_does_not_break_fetch(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    settings = make_settings()
    store = Store.open(blocker / "w.db")
    r = Router(settings, ladder(), memory=Memory(store, settings))
    res = await r.fetch(FetchRequest(url="http://fake.test/p"))
    assert res.strategy_used == "http"
    assert any("memory" in w for w in res.warnings)


async def test_failures_are_recorded_for_all_strategies_failed(data_dir):
    import pytest

    from webfetch2000.models import FetchError

    s = ladder(
        http=[outcome("x", status=403)],
        browser=[outcome("x", status=403)],
        stealth=[outcome("x", status=403)],
    )
    r, store = build(data_dir, s)
    with pytest.raises(FetchError):
        await r.fetch(FetchRequest(url="http://fake.test/p"))
    with store.conn() as c:
        n = c.execute(
            "select count(*) from outcomes where failures > 0 and path_prefix=''"
        ).fetchone()[0]
    assert n == 3
