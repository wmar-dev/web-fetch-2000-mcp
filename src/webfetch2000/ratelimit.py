"""Per-domain concurrency cap + token bucket, and Retry-After parsing."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime


class RateLimitTimeout(Exception):
    """Waiting for a per-domain slot or token would exceed the caller's timeout."""


@dataclass
class Slot:
    waited_ms: float = 0.0


@dataclass
class _Domain:
    sem: asyncio.Semaphore | None
    tokens: float
    last: float = field(default_factory=time.monotonic)


class DomainLimiter:
    """Per-domain ``concurrency`` and ``rate_per_s`` (with ``burst``); 0 disables a limit."""

    def __init__(self, concurrency: int, rate_per_s: float, burst: int) -> None:
        self.concurrency = concurrency
        self.rate = rate_per_s
        self.capacity = float(burst if burst > 0 else 1)
        self._domains: dict[str, _Domain] = {}

    def _get(self, domain: str) -> _Domain:
        d = self._domains.get(domain)
        if d is None:
            sem = asyncio.Semaphore(self.concurrency) if self.concurrency > 0 else None
            d = _Domain(sem=sem, tokens=self.capacity)
            self._domains[domain] = d
        return d

    async def token(self, domain: str, timeout: float) -> float:
        """Take one request token; returns the milliseconds waited."""
        if self.rate <= 0:
            return 0.0
        d = self._get(domain)
        now = time.monotonic()
        d.tokens = min(self.capacity, d.tokens + (now - d.last) * self.rate)
        d.last = now
        wait = 0.0 if d.tokens >= 1 else (1 - d.tokens) / self.rate
        if wait > timeout:
            raise RateLimitTimeout(f"rate limit for {domain}: would wait {wait:.1f}s")
        d.tokens -= 1  # reserve (may go negative) so concurrent callers queue fairly
        if wait > 0:
            await asyncio.sleep(wait)
        return wait * 1000

    @asynccontextmanager
    async def slot(self, domain: str, timeout: float) -> AsyncIterator[Slot]:
        """Hold a concurrency slot and spend a token for one request."""
        started = time.monotonic()
        d = self._get(domain)
        acquired = False
        if d.sem is not None:
            try:
                await asyncio.wait_for(d.sem.acquire(), timeout)
            except TimeoutError as e:
                raise RateLimitTimeout(f"too many concurrent requests to {domain}") from e
            acquired = True
        try:
            remaining = max(0.0, timeout - (time.monotonic() - started))
            await self.token(domain, remaining)
            yield Slot(waited_ms=(time.monotonic() - started) * 1000)
        finally:
            if acquired and d.sem is not None:
                d.sem.release()


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Seconds to wait from a Retry-After header (delta-seconds or HTTP-date)."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    ref = time.time() if now is None else now
    return max(0.0, when.timestamp() - ref)
