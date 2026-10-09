import pytest

from webfetch2000 import safety
from webfetch2000.config import Settings
from webfetch2000.models import FetchError


def test_valid_url_normalized():
    p = safety.validate_url("HTTP://Example.COM:80/a/b?q=1#frag")
    assert p.scheme == "http" and p.host == "example.com"
    assert p.url == "http://example.com/a/b?q=1"  # fragment dropped
    assert p.path == "/a/b" and p.domain == "example.com"


def test_www_stripped_for_domain():
    assert safety.validate_url("https://www.example.com/x").domain == "example.com"


@pytest.mark.parametrize("url", ["", "not a url", "http://", "://x", "http:///path"])
def test_malformed(url):
    with pytest.raises(FetchError) as e:
        safety.validate_url(url)
    assert e.value.code == "invalid_url"


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "ftp://example.com/x", "javascript:alert(1)", "data:text/html,x"]
)
def test_unsupported_scheme(url):
    with pytest.raises(FetchError) as e:
        safety.validate_url(url)
    assert e.value.code == "unsupported_scheme"


def test_userinfo_rejected():
    with pytest.raises(FetchError) as e:
        safety.validate_url("http://user:pass@example.com/")
    assert e.value.code == "invalid_url"


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.4",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "100.64.0.1",
    ],
)
def test_blocked_ips(ip):
    assert safety.is_blocked_ip(ip)


@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_ips_allowed(ip):
    assert not safety.is_blocked_ip(ip)


async def test_ip_literal_private_blocked():
    with pytest.raises(FetchError) as e:
        await safety.ensure_allowed("http://127.0.0.1:8080/x", Settings())
    assert e.value.code == "blocked_address"


async def test_hostname_resolving_to_private_blocked(monkeypatch):
    async def fake(host):
        return ["93.184.216.34", "10.0.0.1"]  # any private result blocks

    monkeypatch.setattr(safety, "_resolve", fake)
    with pytest.raises(FetchError) as e:
        await safety.ensure_allowed("http://rebind.example/x", Settings())
    assert e.value.code == "blocked_address"


async def test_hostname_public_allowed(monkeypatch):
    async def fake(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(safety, "_resolve", fake)
    p = await safety.ensure_allowed("https://example.com/x", Settings())
    assert p.host == "example.com"


async def test_unresolvable_host_is_invalid_url(monkeypatch):
    async def fake(host):
        raise OSError("nope")

    monkeypatch.setattr(safety, "_resolve", fake)
    with pytest.raises(FetchError) as e:
        await safety.ensure_allowed("https://nonexistent.invalid/", Settings())
    assert e.value.code == "invalid_url"


async def test_localhost_name_blocked():
    with pytest.raises(FetchError) as e:
        await safety.ensure_allowed("http://localhost:3000/", Settings())
    assert e.value.code == "blocked_address"


async def test_allow_private_flag():
    s = Settings(allow_private_addresses=True)
    p = await safety.ensure_allowed("http://127.0.0.1:8080/x", s)
    assert p.host == "127.0.0.1"


async def test_redirect_hop_rechecked(monkeypatch):
    async def fake(host):
        return ["10.1.1.1"] if host == "internal.example" else ["93.184.216.34"]

    monkeypatch.setattr(safety, "_resolve", fake)
    s = Settings()
    await safety.ensure_allowed("https://public.example/", s)
    with pytest.raises(FetchError) as e:
        await safety.ensure_allowed("https://internal.example/admin", s)
    assert e.value.code == "blocked_address"


async def test_deny_and_allow_domains(monkeypatch):
    async def fake(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(safety, "_resolve", fake)
    with pytest.raises(FetchError) as e:
        await safety.ensure_allowed("https://bad.example/", Settings(deny_domains=("bad.example",)))
    assert e.value.code == "blocked_address"
    with pytest.raises(FetchError):
        await safety.ensure_allowed(
            "https://other.example/", Settings(allow_domains=("good.example",))
        )
    await safety.ensure_allowed("https://good.example/", Settings(allow_domains=("good.example",)))


def test_path_prefix():
    assert safety.path_prefix("/docs/a/b") == "/docs"
    assert safety.path_prefix("/") == ""
    assert safety.path_prefix("") == ""
