"""Plain async HTTP strategy (cheapest). Browser-like identity, markdown negotiation."""

from __future__ import annotations

import time
from urllib.parse import urljoin

import httpx

from ..config import Settings
from ..models import FetchError
from ..ratelimit import DomainLimiter, RateLimitTimeout
from ..safety import ensure_allowed, is_blocked_ip
from .base import FetchOutcome, Strategy, StrategyError, StrategyRequest

_REDIRECTS = {301, 302, 303, 307, 308}
_ACCEPT_MARKDOWN = "text/markdown, text/html;q=0.9, application/xhtml+xml;q=0.9, */*;q=0.8"
_ACCEPT_HTML = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
)


class HttpStrategy(Strategy):
    name = "http"
    cost = 1

    def __init__(self, settings: Settings, limiter: DomainLimiter | None) -> None:
        self.settings = settings
        self.limiter = limiter
        self._client: httpx.AsyncClient | None = None

    async def available(self) -> tuple[bool, str | None]:
        return True, None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            try:
                self._client = httpx.AsyncClient(http2=True, follow_redirects=False)
            except ImportError:  # h2 missing
                self._client = httpx.AsyncClient(follow_redirects=False)
        return self._client

    def _headers(self, req: StrategyRequest) -> dict[str, str]:
        h = {
            "User-Agent": self.settings.user_agent,
            "Accept": _ACCEPT_MARKDOWN if req.negotiate_markdown else _ACCEPT_HTML,
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
        h.update(self.settings.extra_headers)
        h.update(req.conditional_headers)
        return h

    async def fetch(self, req: StrategyRequest) -> FetchOutcome:
        started = time.monotonic()
        client = self._get_client()
        headers = self._headers(req)
        url = req.url
        hops = 0
        waited = 0.0
        while True:
            parsed = await ensure_allowed(url, self.settings)  # SSRF check on every hop
            outcome, location, hop_wait = await self._hop(
                client, parsed.domain, parsed.url, headers, req
            )
            waited += hop_wait
            if location is not None:
                hops += 1
                if hops > self.settings.max_redirects:
                    raise StrategyError(
                        "too_many_redirects", f"more than {self.settings.max_redirects} redirects"
                    )
                url = urljoin(parsed.url, location)
                continue
            assert outcome is not None
            outcome.waited_ms = waited
            outcome.duration_ms = int((time.monotonic() - started) * 1000)
            return outcome

    async def _hop(
        self,
        client: httpx.AsyncClient,
        domain: str,
        url: str,
        headers: dict[str, str],
        req: StrategyRequest,
    ) -> tuple[FetchOutcome | None, str | None, float]:
        """One request under the per-domain limiter: (outcome, redirect-location, waited_ms)."""
        try:
            if self.limiter is None:
                outcome, location = await self._request(client, url, headers, req)
                return outcome, location, 0.0
            async with self.limiter.slot(domain, req.timeout_s) as slot:
                outcome, location = await self._request(client, url, headers, req)
                return outcome, location, slot.waited_ms
        except RateLimitTimeout as e:
            raise FetchError("rate_limited", str(e)) from e

    async def _request(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        req: StrategyRequest,
    ) -> tuple[FetchOutcome | None, str | None]:
        try:
            async with client.stream(
                "GET", url, headers=headers, timeout=httpx.Timeout(req.timeout_s)
            ) as resp:
                self._check_peer(resp)
                loc = resp.headers.get("location")
                if resp.status_code in _REDIRECTS and loc:
                    return None, loc
                body, truncated, total = await _read_capped(resp, req.max_bytes)
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                return (
                    FetchOutcome(
                        status=resp.status_code,
                        final_url=str(resp.url),
                        headers=hdrs,
                        body=body,
                        content_type=hdrs.get("content-type", ""),
                        body_truncated=truncated,
                        total_bytes=total,
                    ),
                    None,
                )
        except httpx.TimeoutException as e:
            raise StrategyError("timeout", f"timed out after {req.timeout_s}s") from e
        except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as e:
            raise StrategyError("connect_error", str(e) or type(e).__name__, retriable=True) from e
        except httpx.HTTPError as e:
            raise StrategyError("http_error", str(e) or type(e).__name__) from e

    def _check_peer(self, resp: httpx.Response) -> None:
        """Defend against DNS rebinding: the address we actually connected to must be public."""
        if self.settings.allow_private_addresses:
            return
        stream = resp.extensions.get("network_stream")
        addr = stream.get_extra_info("server_addr") if stream is not None else None
        if addr and is_blocked_ip(str(addr[0])):
            raise FetchError(
                "blocked_address", f"connection went to a local or private address ({addr[0]})"
            )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


async def _read_capped(resp: httpx.Response, max_bytes: int) -> tuple[bytes, bool, int | None]:
    declared = resp.headers.get("content-length")
    total = int(declared) if declared and declared.isdigit() else None
    buf = bytearray()
    truncated = False
    async for chunk in resp.aiter_bytes():
        room = max_bytes - len(buf)
        if len(chunk) >= room:
            buf.extend(chunk[:room])
            truncated = True
            break
        buf.extend(chunk)
    return bytes(buf), truncated, total
