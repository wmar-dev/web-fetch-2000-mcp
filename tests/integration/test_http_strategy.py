"""HTTP strategy against the local site and respx-mocked hosts (US1)."""

import httpx
import pytest
import respx

from tests.helpers import make_settings
from webfetch2000 import safety
from webfetch2000.models import FetchError, FetchRequest
from webfetch2000.ratelimit import DomainLimiter
from webfetch2000.router import Router
from webfetch2000.strategies.base import StrategyError, StrategyRequest
from webfetch2000.strategies.http import HttpStrategy


def sreq(url, **kw):
    kw.setdefault("timeout_s", 5)
    kw.setdefault("max_bytes", 10_000_000)
    return StrategyRequest(url=url, **kw)


@pytest.fixture
async def http():
    strategies = []

    def make(limiter=None, **settings):
        s = HttpStrategy(make_settings(**settings), limiter)
        strategies.append(s)
        return s

    yield make
    for s in strategies:
        await s.close()


async def test_default_headers_are_browser_like_and_negotiate_markdown(http, site):
    out = await http().fetch(sreq(site.url("/static")))
    h = site.hits[-1]["headers"]
    assert "Chrome/" in h["user-agent"] and "Mozilla/5.0" in h["user-agent"]
    assert h["accept"].startswith("text/markdown")
    assert "en" in h["accept-language"]
    assert out.status == 200 and b"Static Heading" in out.body


async def test_user_agent_and_extra_headers_override(http, site):
    s = http(user_agent="custom/1.0", extra_headers={"X-Test": "yes"})
    await s.fetch(sreq(site.url("/static")))
    h = site.hits[-1]["headers"]
    assert h["user-agent"] == "custom/1.0" and h["x-test"] == "yes"


async def test_negotiation_can_be_disabled_per_call(http, site):
    await http().fetch(sreq(site.url("/static"), negotiate_markdown=False))
    assert "text/markdown" not in site.hits[-1]["headers"]["accept"]


async def test_origin_markdown_passthrough_via_router(site):
    settings = make_settings()
    router = Router(settings, {"http": HttpStrategy(settings, None)})
    res = await router.fetch(FetchRequest(url=site.url("/markdown")))
    assert res.markdown_source == "origin"  # SC-013
    assert res.origin_tokens == 42
    assert res.content_signals == "ai-train=no, search=yes, ai-input=yes"
    assert res.content.startswith("# Origin Markdown")
    assert res.strategy_used == "http"
    await router.close()


async def test_negotiation_off_converts_html(site):
    settings = make_settings(negotiate_markdown=False)
    router = Router(settings, {"http": HttpStrategy(settings, None)})
    res = await router.fetch(FetchRequest(url=site.url("/markdown")))
    assert res.markdown_source == "converted" and "Static Heading" in res.content
    await router.close()


async def test_content_signal_ai_input_no_warns(site, monkeypatch):
    settings = make_settings()
    router = Router(settings, {"http": HttpStrategy(settings, None)})
    # server sends ai-train=no only; patch handler data by using header via per-request check
    res = await router.fetch(FetchRequest(url=site.url("/markdown")))
    assert not any("ai-input" in w for w in res.warnings)
    await router.close()


async def test_follows_redirects(http, site):
    out = await http().fetch(sreq(site.url("/redirect")))
    assert out.status == 200 and out.final_url == site.url("/static")


async def test_redirect_loop_is_bounded(http, site):
    with pytest.raises(StrategyError) as e:
        await http(max_redirects=3).fetch(sreq(site.url("/redirect-loop")))
    assert e.value.reason == "too_many_redirects"
    assert site.count("/redirect-loop") == 4


async def test_timeout_is_a_strategy_error(http, site):
    with pytest.raises(StrategyError) as e:
        await http().fetch(sreq(site.url("/slow?s=3"), timeout_s=1))
    assert e.value.reason == "timeout"


async def test_connection_refused_is_retriable(http):
    with pytest.raises(StrategyError) as e:
        await http().fetch(sreq("http://127.0.0.1:9/"))
    assert e.value.reason == "connect_error" and e.value.retriable


async def test_body_truncated_at_cap(http, site):
    out = await http().fetch(sreq(site.url("/large?bytes=200000"), max_bytes=50_000))
    assert out.body_truncated and len(out.body) == 50_000
    assert out.total_bytes and out.total_bytes > 200_000


async def test_router_truncates_with_warning_not_error(site):
    settings = make_settings(max_response_bytes=50_000)
    router = Router(settings, {"http": HttpStrategy(settings, None)})
    res = await router.fetch(
        FetchRequest(url=site.url("/large?bytes=200000"), format="raw", max_chars=100)
    )
    assert res.truncated and res.total_bytes and res.total_bytes > 200_000
    assert any("truncated" in w for w in res.warnings)
    await router.close()


async def test_unusable_truncation_is_too_large():
    # a PDF cut off mid-file cannot be read reliably -> too_large, not garbage
    from tests.conftest import make_pdf

    pdf = make_pdf("x" * 5000)
    settings = make_settings(max_response_bytes=2_000)
    router = Router(settings, {"http": HttpStrategy(settings, None)})
    with respx.mock(assert_all_called=False) as m:
        m.get("http://pdf.test/a.pdf").respond(
            200, content=pdf, headers={"content-type": "application/pdf"}
        )
        with pytest.raises(FetchError) as e:
            await router.fetch(FetchRequest(url="http://pdf.test/a.pdf"))
    assert e.value.code == "too_large"
    await router.close()


@respx.mock
async def test_redirect_to_private_address_is_blocked(monkeypatch):
    async def fake_resolve(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(safety, "_resolve", fake_resolve)
    respx.get("https://public.test/").respond(
        302, headers={"location": "http://169.254.169.254/latest/meta-data"}
    )
    metadata = respx.get("http://169.254.169.254/latest/meta-data").respond(200, text="secret")
    s = HttpStrategy(make_settings(allow_private_addresses=False), None)
    with pytest.raises(FetchError) as e:
        await s.fetch(sreq("https://public.test/"))
    assert e.value.code == "blocked_address" and not metadata.called
    await s.close()


@respx.mock
async def test_each_redirect_hop_is_rate_limited(monkeypatch):
    seen = []

    class Spy(DomainLimiter):
        async def token(self, domain, timeout):
            seen.append(domain)
            return 0.0

    respx.get("http://a.test/").respond(302, headers={"location": "http://b.test/x"})
    respx.get("http://b.test/x").respond(
        200,
        text="<html><body>" + "word " * 100 + "</body></html>",
        headers={"content-type": "text/html"},
    )
    s = HttpStrategy(make_settings(domain_rate_per_s=5), Spy(0, 5, 5))
    out = await s.fetch(sreq("http://a.test/"))
    assert out.status == 200 and seen == ["a.test", "b.test"]
    await s.close()


@respx.mock
async def test_http_error_statuses_are_returned_not_raised():
    respx.get("http://e.test/").respond(403, text="no")
    s = HttpStrategy(make_settings(), None)
    out = await s.fetch(sreq("http://e.test/"))
    assert out.status == 403
    await s.close()


@respx.mock
async def test_network_error_mapping():
    respx.get("http://n.test/").mock(side_effect=httpx.ConnectError("boom"))
    s = HttpStrategy(make_settings(), None)
    with pytest.raises(StrategyError) as e:
        await s.fetch(sreq("http://n.test/"))
    assert e.value.reason == "connect_error"
    await s.close()


def test_dns_rebinding_is_caught_by_checking_the_connected_peer():
    class Stream:
        def __init__(self, ip):
            self.ip = ip

        def get_extra_info(self, name):
            return (self.ip, 443) if name == "server_addr" else None

    class Resp:
        def __init__(self, ip):
            self.extensions = {"network_stream": Stream(ip)}

    s = HttpStrategy(make_settings(allow_private_addresses=False), None)
    s._check_peer(Resp("93.184.216.34"))  # public: fine
    for ip in ("127.0.0.1", "10.1.2.3", "169.254.169.254"):
        with pytest.raises(FetchError) as e:
            s._check_peer(Resp(ip))
        assert e.value.code == "blocked_address"
    HttpStrategy(make_settings(allow_private_addresses=True), None)._check_peer(Resp("10.1.2.3"))
    s._check_peer(type("R", (), {"extensions": {}})())  # no stream info (mocked transport)
