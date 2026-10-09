import pytest

from webfetch2000.config import Settings
from webfetch2000.memory import Memory
from webfetch2000.store import Store

LADDER = ["http", "browser", "stealth"]
T0 = 1_700_000_000.0
DAY = 86400.0


@pytest.fixture
def mem(data_dir):
    def make(**kw):
        return Memory(Store.open(data_dir / "m.db"), Settings(**kw), rng=lambda: 0.99)

    return make


def rec(m, strategy, ok, n=1, domain="a.com", path="/x", at=T0, ms=100):
    for _ in range(n):
        m.record(domain, path, strategy, ok, ms, now=at)


def test_unseen_site_uses_ladder_order(mem):
    plan = mem().plan("new.com", "/", LADDER, now=T0)
    assert plan.order == LADDER and plan.start == "http"
    assert "no history" in plan.reason


def test_laplace_scores(mem):
    m = mem()
    rec(m, "browser", True, 2)
    rec(m, "http", False, 2)
    scores = {s.strategy: s for s in m.scores("a.com", "", LADDER, now=T0)}
    assert scores["browser"].score == pytest.approx(0.75)
    assert scores["http"].score == pytest.approx(0.25)
    assert scores["stealth"].score == 0.5 and scores["stealth"].observations == 0


def test_below_min_observations_is_prior(mem):
    m = mem(min_observations=2)
    rec(m, "http", False, 1)
    s = {x.strategy: x for x in m.scores("a.com", "", LADDER, now=T0)}
    assert s["http"].score == 0.5  # one failure is not enough to give up on http
    assert m.plan("a.com", "/x", LADDER, now=T0).start == "http"


def test_switches_start_after_enough_failures(mem):
    m = mem()
    rec(m, "http", False, 2)
    rec(m, "browser", True, 2)
    plan = m.plan("a.com", "/x", LADDER, now=T0)
    assert plan.start == "browser"
    assert plan.order == ["browser", "stealth", "http"]  # cheaper strategies go last


def test_cheapest_within_tolerance_wins(mem):
    m = mem(score_tolerance=0.1)
    rec(m, "http", True, 5)
    rec(m, "http", False, 1)  # 6/9 ~ .67... still within .1 of browser's
    rec(m, "browser", True, 6)
    # http: s=5,f=1 -> 6/8=.75 ; browser: s=6 -> 7/8=.875 ; diff .125 > .1 -> browser
    assert m.plan("a.com", "/x", LADDER, now=T0).start == "browser"
    m2 = mem(score_tolerance=0.2)
    assert m2.plan("a.com", "/x", LADDER, now=T0).start == "http"


def test_counters_decay_with_half_life(mem):
    m = mem(half_life_days=14)
    rec(m, "http", True, 4)
    fresh = m.scores("a.com", "", LADDER, now=T0)[0]
    later = m.scores("a.com", "", LADDER, now=T0 + 14 * DAY)[0]
    assert fresh.successes == pytest.approx(4)
    assert later.successes == pytest.approx(2, rel=1e-3)
    assert later.score < fresh.score


def test_old_failures_fade_so_site_is_retried(mem):
    m = mem(half_life_days=1)
    rec(m, "http", False, 4)
    rec(m, "browser", True, 4)
    assert m.plan("a.com", "/x", LADDER, now=T0).start == "browser"
    # a month later the evidence has decayed toward the prior for both
    old = m.scores("a.com", "", LADDER, now=T0 + 30 * DAY)
    assert all(abs(s.score - 0.5) < 0.01 for s in old if s.strategy in ("http", "browser"))


def test_mean_duration_is_a_moving_average(mem):
    m = mem()
    rec(m, "http", True, 1, ms=100)
    rec(m, "http", True, 1, ms=200)
    s = m.scores("a.com", "", LADDER, now=T0)[0]
    assert 100 < s.mean_duration_ms < 200


def test_records_domain_level_and_prefix_rows(mem):
    m = mem()
    rec(m, "http", True, 1, path="/docs/guide")
    with m.store.conn() as c:
        rows = c.execute("select path_prefix from outcomes order by path_prefix").fetchall()
    assert [r[0] for r in rows] == ["", "/docs"]


def test_root_path_records_only_domain_row(mem):
    m = mem()
    rec(m, "http", True, 1, path="/")
    with m.store.conn() as c:
        assert c.execute("select count(*) from outcomes").fetchone()[0] == 1


def test_reset_one_domain_and_all(mem):
    m = mem()
    rec(m, "http", True, 1, domain="a.com")
    rec(m, "http", True, 1, domain="b.com")
    assert m.reset("a.com") == 1
    assert m.plan("a.com", "/", LADDER, now=T0).reason.startswith("no history")
    assert m.plan("b.com", "/", LADDER, now=T0).reason != "no history"
    assert m.reset() >= 1
    assert m.snapshot("b.com", None, LADDER, now=T0)["ranking"][0]["observations"] == 0


def test_snapshot_shape(mem):
    m = mem()
    rec(m, "http", False, 2)
    rec(m, "browser", True, 2)
    snap = m.snapshot("a.com", "/x", LADDER, now=T0)
    assert snap["domain"] == "a.com"
    assert [r["strategy"] for r in snap["ranking"]] == ["browser", "stealth", "http"]
    first = snap["ranking"][0]
    assert {
        "strategy",
        "score",
        "successes",
        "failures",
        "mean_duration_ms",
        "last_attempt_at",
    } <= set(first)
    assert snap["next_start_strategy"] == "browser"
