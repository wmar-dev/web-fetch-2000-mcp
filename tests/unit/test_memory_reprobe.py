import pytest

from webfetch2000.config import Settings
from webfetch2000.memory import Memory
from webfetch2000.store import Store

LADDER = ["http", "browser", "stealth"]
T0 = 1_700_000_000.0
DAY = 86400.0


def make(data_dir, rng=lambda: 0.99, **kw):
    return Memory(Store.open(data_dir / "r.db"), Settings(**kw), rng=rng)


def seed(m, at):
    for _ in range(3):
        m.record("s.com", "/x", "http", False, 50, now=at)
        m.record("s.com", "/x", "browser", True, 50, now=at)


def test_stale_cheaper_strategy_is_reprobed(data_dir):
    m = make(data_dir, reprobe_after_days=7, half_life_days=365)
    seed(m, T0)
    plan = m.plan("s.com", "/x", LADDER, now=T0 + 8 * DAY)
    assert plan.reprobe == "http" and plan.order[0] == "http"
    assert plan.order[1:] == ["browser", "stealth"]
    assert "re-test" in plan.reason


def test_recent_failure_not_reprobed_when_rng_high(data_dir):
    m = make(data_dir, reprobe_after_days=7, half_life_days=365, rng=lambda: 0.99)
    seed(m, T0)
    plan = m.plan("s.com", "/x", LADDER, now=T0 + 1 * DAY)
    assert plan.reprobe is None and plan.start == "browser"


def test_random_reprobe_with_probability(data_dir):
    m = make(data_dir, reprobe_probability=0.05, half_life_days=365, rng=lambda: 0.01)
    seed(m, T0)
    plan = m.plan("s.com", "/x", LADDER, now=T0 + DAY)
    assert plan.reprobe == "http"


def test_reprobe_disabled_when_probability_zero_and_recent(data_dir):
    m = make(data_dir, reprobe_probability=0.0, half_life_days=365, rng=lambda: 0.0)
    seed(m, T0)
    assert m.plan("s.com", "/x", LADDER, now=T0 + DAY).reprobe is None


def test_no_reprobe_when_start_is_already_cheapest(data_dir):
    m = make(data_dir, rng=lambda: 0.0)
    for _ in range(3):
        m.record("s.com", "/x", "http", True, 50, now=T0)
    assert m.plan("s.com", "/x", LADDER, now=T0 + 30 * DAY).reprobe is None


def test_memory_recovers_after_site_changes(data_dir):
    m = make(data_dir, reprobe_after_days=7, half_life_days=14)
    seed(m, T0)
    t = T0 + 8 * DAY
    assert m.plan("s.com", "/x", LADDER, now=t).reprobe == "http"
    for _ in range(6):  # the probes succeed: the site dropped its protection
        m.record("s.com", "/x", "http", True, 50, now=t)
    plan = m.plan("s.com", "/x", LADDER, now=t)
    assert plan.start == "http" and plan.reprobe is None


def test_reprobes_cheapest_due_strategy_first(data_dir):
    m = make(data_dir, reprobe_after_days=7, half_life_days=365)
    for _ in range(3):
        m.record("s.com", "/x", "http", False, 50, now=T0)
        m.record("s.com", "/x", "browser", False, 50, now=T0)
        m.record("s.com", "/x", "stealth", True, 50, now=T0)
    plan = m.plan("s.com", "/x", LADDER, now=T0 + 10 * DAY)
    assert plan.reprobe == "http" and plan.order == ["http", "stealth", "browser"]
    assert pytest.approx(0) == 0
