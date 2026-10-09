import pytest

from webfetch2000.config import Settings
from webfetch2000.memory import Memory
from webfetch2000.store import Store

LADDER = ["http", "browser", "stealth"]
T0 = 1_700_000_000.0


@pytest.fixture
def mem(data_dir):
    def make(**kw):
        return Memory(Store.open(data_dir / "o.db"), Settings(**kw), rng=lambda: 0.99)

    return make


def rec(m, strategy, ok, n, path):
    for _ in range(n):
        m.record("site.com", path, strategy, ok, 50, now=T0)


def test_no_override_without_enough_observations(mem):
    m = mem(override_min_observations=5)
    rec(m, "http", True, 20, "/blog/a")
    rec(m, "http", False, 3, "/app/x")
    rec(m, "browser", True, 1, "/app/x")
    plan = m.plan("site.com", "/app/y", LADDER, now=T0)
    assert plan.scope == "" and plan.start == "http"


def test_override_created_when_section_differs(mem):
    m = mem(override_min_observations=5)
    rec(m, "http", True, 30, "/blog/a")
    rec(m, "http", False, 6, "/app/x")
    rec(m, "browser", True, 6, "/app/x")
    app = m.plan("site.com", "/app/dashboard", LADDER, now=T0)
    assert app.scope == "/app" and app.start == "browser"
    blog = m.plan("site.com", "/blog/other", LADDER, now=T0)
    assert blog.scope == "" and blog.start == "http"
    root = m.plan("site.com", "/", LADDER, now=T0)
    assert root.start == "http"


def test_override_removed_when_section_converges(mem):
    m = mem(override_min_observations=5)
    rec(m, "http", False, 6, "/app/x")
    rec(m, "browser", True, 6, "/app/x")
    rec(m, "http", True, 40, "/blog/a")
    assert m.plan("site.com", "/app/z", LADDER, now=T0).scope == "/app"
    # the section starts working over plain HTTP again
    rec(m, "http", True, 30, "/app/x")
    plan = m.plan("site.com", "/app/z", LADDER, now=T0)
    assert plan.start == "http" and plan.scope == ""


def test_listed_in_snapshot(mem):
    m = mem(override_min_observations=5)
    rec(m, "http", True, 30, "/blog/a")
    rec(m, "http", False, 6, "/app/x")
    rec(m, "browser", True, 6, "/app/x")
    snap = m.snapshot("site.com", None, LADDER, now=T0)
    assert [o["path_prefix"] for o in snap["overrides"]] == ["/app"]
    assert snap["overrides"][0]["ranking"][0]["strategy"] == "browser"


def test_prefix_rows_are_pruned(mem):
    m = mem(max_prefixes_per_domain=3)
    for i in range(6):
        m.record("site.com", f"/p{i}/x", "http", True, 10, now=T0 + i)
    with m.store.conn() as c:
        prefixes = {r[0] for r in c.execute("select distinct path_prefix from outcomes") if r[0]}
    assert len(prefixes) == 3
    assert prefixes == {"/p3", "/p4", "/p5"}  # most recently used kept
