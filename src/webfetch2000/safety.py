"""URL validation and private-network blocking (SSRF protection)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from .config import Settings
from .models import FetchError

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class ParsedURL:
    url: str
    scheme: str
    host: str
    port: int | None
    path: str
    domain: str


def _domain_of(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def validate_url(url: str) -> ParsedURL:
    """Syntactic validation and normalization (no network access)."""
    raw = (url or "").strip()
    if not raw:
        raise FetchError("invalid_url", "URL is empty")
    try:
        parts = urlsplit(raw)
        port = parts.port
        host = parts.hostname
    except ValueError as e:
        raise FetchError("invalid_url", f"URL is malformed: {e}") from e
    scheme = parts.scheme.lower()
    if not scheme:
        raise FetchError("invalid_url", "URL has no scheme (expected http:// or https://)")
    if scheme not in _DEFAULT_PORTS:
        raise FetchError(
            "unsupported_scheme", f"scheme '{scheme}' is not supported; use http or https"
        )
    if not host:
        raise FetchError("invalid_url", "URL has no host")
    if parts.username is not None or parts.password is not None:
        raise FetchError("invalid_url", "URLs with embedded credentials are not supported")
    host = host.lower().rstrip(".")
    netloc = f"[{host}]" if ":" in host else host
    if port and port != _DEFAULT_PORTS[scheme]:
        netloc = f"{netloc}:{port}"
    path = parts.path or "/"
    normalized = urlunsplit((scheme, netloc, path, parts.query, ""))
    return ParsedURL(
        url=normalized, scheme=scheme, host=host, port=port, path=path, domain=_domain_of(host)
    )


def is_blocked_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return (
        not addr.is_global
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
    )


async def _resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(i[4][0]) for i in infos})


def _domain_matches(host: str, patterns: tuple[str, ...]) -> bool:
    return any(host == p or host.endswith("." + p) for p in (p.lower() for p in patterns))


async def ensure_allowed(url: str, settings: Settings) -> ParsedURL:
    """Validate ``url`` and make sure it does not point at a local or private address."""
    parsed = validate_url(url)
    host = parsed.host
    if _domain_matches(host, settings.deny_domains):
        raise FetchError("blocked_address", f"domain '{host}' is on the deny list")
    if settings.allow_domains and not _domain_matches(host, settings.allow_domains):
        raise FetchError("blocked_address", f"domain '{host}' is not on the allow list")
    if settings.allow_private_addresses:
        return parsed

    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False

    if is_literal:
        if is_blocked_ip(host):
            raise FetchError("blocked_address", f"address {host} is local or private")
        return parsed
    if host == "localhost" or host.endswith(".localhost"):
        raise FetchError("blocked_address", "localhost is blocked")
    try:
        ips = await _resolve(host)
    except OSError as e:
        raise FetchError("invalid_url", f"could not resolve host '{host}': {e}") from e
    if not ips:
        raise FetchError("invalid_url", f"host '{host}' did not resolve")
    for ip in ips:
        if is_blocked_ip(ip):
            raise FetchError(
                "blocked_address", f"host '{host}' resolves to a local or private address"
            )
    return parsed


def path_prefix(path: str) -> str:
    """First path segment used for learned per-section overrides ('' for the root)."""
    seg = [s for s in (path or "").split("/") if s]
    return f"/{seg[0]}" if seg else ""
