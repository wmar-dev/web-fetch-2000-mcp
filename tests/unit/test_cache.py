import pytest

from webfetch2000.cache import Cache, ttl_for
from webfetch2000.config import Settings
from webfetch2000.models import Fetched
from webfetch2000.store import Store, StoreUnavailable

T0 = 1_700_000_000.0


def fetched(body="# hi", **kw):
    base = dict(
        final_url="http://a.test/x",
        status=200,
        content_type="text/html",
        markdown=body,
        kind="html",
        raw=body.encode(),
        raw_truncated=False,
        total_bytes=len(body),
        strategy_used="http",
        attempts=[],
    )
    base.update(kw)
    return Fetched(**base)


@pytest.fixture
def make(data_dir):
    def _make(**kw):
        return Cache(Store.open(data_dir / "c.db"), Settings(**kw))

    return _make


def test_key_depends_on_url_and_negotiation():
    k = Cache.key("http://a.test/x", True)
    assert k == Cache.key("http://a.test/x", True)
    assert k != Cache.key("http://a.test/y", True)
    assert k != Cache.key("http://a.test/x", False)


def test_roundtrip_fresh(make):
    c = make(cache_ttl_s=60)
    k = Cache.key("http://a.test/x", True)
    assert c.get(k, now=T0) == (None, "miss")
    assert c.put(k, "http://a.test/x", "a.test", fetched(), now=T0)
    entry, state = c.get(k, now=T0 + 30)
    assert state == "fresh" and entry is not None
    assert entry.markdown == "# hi" and entry.raw == b"# hi" and entry.strategy_used == "http"
    f = entry.to_fetched()
    assert (
        f.markdown == "# hi"
        and f.final_url == "http://a.test/x"
        and f.markdown_source == "converted"
    )


def test_expiry_without_validators_is_a_miss_and_removed(make):
    c = make(cache_ttl_s=60)
    k = Cache.key("http://a.test/x", True)
    c.put(k, "http://a.test/x", "a.test", fetched(), now=T0)
    assert c.get(k, now=T0 + 61) == (None, "miss")
    with c.store.conn() as conn:
        assert conn.execute("select count(*) from cache").fetchone()[0] == 0


def test_expired_with_validators_is_stale_not_dropped(make):
    c = make(cache_ttl_s=60)
    k = Cache.key("http://a.test/x", True)
    c.put(k, "http://a.test/x", "a.test", fetched(etag='"v1"'), now=T0)
    entry, state = c.get(k, now=T0 + 120)
    assert state == "stale" and entry.etag == '"v1"'


def test_touch_extends_expiry(make):
    c = make(cache_ttl_s=60)
    k = Cache.key("http://a.test/x", True)
    c.put(k, "http://a.test/x", "a.test", fetched(etag='"v1"'), now=T0)
    c.touch(k, {}, now=T0 + 120)
    assert c.get(k, now=T0 + 150)[1] == "fresh"


@pytest.mark.parametrize(
    "header,has_validators,expected",
    [
        (None, False, 3600),
        ("max-age=120", False, 120),
        ("public, max-age=5", False, 5),
        ("no-store", True, None),
        ("private, no-store", False, None),
        ("no-cache", False, None),  # revalidate-only needs validators
        ("no-cache", True, 0),
        ("max-age=0", True, 0),
        ("max-age=0", False, None),
    ],
)
def test_ttl_for(header, has_validators, expected):
    assert ttl_for(header, has_validators, Settings()) == expected


def test_cache_control_ignored_when_disabled():
    s = Settings(respect_cache_control=False)
    assert ttl_for("no-store", False, s) == 3600


def test_no_store_not_written(make):
    c = make()
    k = Cache.key("http://a.test/x", True)
    assert not c.put(k, "http://a.test/x", "a.test", fetched(cache_control="no-store"), now=T0)
    assert c.get(k, now=T0) == (None, "miss")


def test_max_age_sets_expiry(make):
    c = make(cache_ttl_s=3600)
    k = Cache.key("http://a.test/x", True)
    c.put(k, "http://a.test/x", "a.test", fetched(cache_control="max-age=1"), now=T0)
    assert c.get(k, now=T0 + 0.5)[1] == "fresh"
    assert c.get(k, now=T0 + 2) == (None, "miss")


def test_lru_eviction_to_size_cap(make):
    c = make(cache_max_mb=1)
    body = "x" * 150_000  # markdown + raw ~ 300 KB per entry
    keys = [Cache.key(f"http://a.test/{i}", True) for i in range(4)]
    for i in range(3):
        c.put(keys[i], f"http://a.test/{i}", "a.test", fetched(body), now=T0 + i)
    c.get(keys[0], now=T0 + 2.5)  # entry 1 is now the least recently used
    c.put(keys[3], "http://a.test/3", "a.test", fetched(body), now=T0 + 3)
    assert c.get(keys[1], now=T0 + 4)[0] is None  # evicted
    for k in (keys[0], keys[2], keys[3]):
        assert c.get(k, now=T0 + 4)[0] is not None
    assert c.total_bytes() <= 1024 * 1024


def test_clear_by_url_domain_and_all(make):
    c = make()
    for u, d in [
        ("http://a.test/1", "a.test"),
        ("http://a.test/2", "a.test"),
        ("http://b.test/1", "b.test"),
    ]:
        c.put(Cache.key(u, True), u, d, fetched(), now=T0)
        c.put(Cache.key(u, False), u, d, fetched(), now=T0)
    assert c.clear(url="http://a.test/1") == 2
    assert c.clear(domain="a.test") == 2
    assert c.clear() == 2
    assert c.total_bytes() == 0


def test_binary_entries_roundtrip(make):
    c = make()
    k = Cache.key("http://a.test/i.png", True)
    f = fetched("", kind="binary", raw=b"\x89PNG\x00", content_type="image/png", total_bytes=5)
    c.put(k, "http://a.test/i.png", "a.test", f, now=T0)
    back = c.get(k, now=T0)[0].to_fetched()
    assert back.kind == "binary" and back.raw == b"\x89PNG\x00" and back.markdown_source is None


def test_unavailable_store_raises(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("x")
    c = Cache(Store.open(blocker / "c.db"), Settings())
    with pytest.raises(StoreUnavailable):
        c.get("k")
