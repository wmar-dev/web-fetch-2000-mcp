import asyncio
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from webfetch2000.ratelimit import DomainLimiter, RateLimitTimeout, parse_retry_after


async def test_concurrency_cap():
    lim = DomainLimiter(concurrency=2, rate_per_s=0, burst=0)
    active = 0
    peak = 0

    async def work():
        nonlocal active, peak
        async with lim.slot("a.com", timeout=5):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1

    await asyncio.gather(*[work() for _ in range(10)])
    assert peak == 2


async def test_domains_are_independent():
    lim = DomainLimiter(concurrency=1, rate_per_s=0, burst=0)
    async with lim.slot("a.com", timeout=1):
        async with lim.slot("b.com", timeout=1):
            pass


async def test_token_bucket_rate_and_burst():
    lim = DomainLimiter(concurrency=0, rate_per_s=20, burst=2)
    t0 = time.monotonic()
    for _ in range(2):  # burst is immediate
        await lim.token("a.com", timeout=1)
    assert time.monotonic() - t0 < 0.03
    t1 = time.monotonic()
    for _ in range(4):  # then 20/s => ~50ms apart
        await lim.token("a.com", timeout=1)
    assert 0.12 <= time.monotonic() - t1 < 0.5


async def test_zero_disables_limits():
    lim = DomainLimiter(concurrency=0, rate_per_s=0, burst=0)
    t0 = time.monotonic()
    await asyncio.gather(*[lim.token("a.com", timeout=1) for _ in range(50)])
    async with lim.slot("a.com", timeout=1):
        pass
    assert time.monotonic() - t0 < 0.2


async def test_queue_bounded_by_timeout():
    lim = DomainLimiter(concurrency=1, rate_per_s=0, burst=0)
    async with lim.slot("a.com", timeout=1):
        t0 = time.monotonic()
        with pytest.raises(RateLimitTimeout):
            async with lim.slot("a.com", timeout=0.1):
                pass
        assert time.monotonic() - t0 < 0.5


async def test_token_wait_exceeding_timeout_raises():
    lim = DomainLimiter(concurrency=0, rate_per_s=1, burst=1)
    await lim.token("a.com", timeout=1)
    with pytest.raises(RateLimitTimeout):
        await lim.token("a.com", timeout=0.05)


async def test_slot_released_on_error():
    lim = DomainLimiter(concurrency=1, rate_per_s=0, burst=0)
    with pytest.raises(RuntimeError):
        async with lim.slot("a.com", timeout=1):
            raise RuntimeError("x")
    async with lim.slot("a.com", timeout=0.1):
        pass


async def test_waited_ms_reported():
    lim = DomainLimiter(concurrency=1, rate_per_s=0, burst=0)

    async def hold():
        async with lim.slot("a.com", timeout=1):
            await asyncio.sleep(0.1)

    task = asyncio.create_task(hold())
    await asyncio.sleep(0.01)
    async with lim.slot("a.com", timeout=1) as slot:
        assert slot.waited_ms >= 50
    await task


def test_parse_retry_after_seconds():
    assert parse_retry_after("7") == 7
    assert parse_retry_after(" 2.5 ") == 2.5
    assert parse_retry_after("-3") == 0
    assert parse_retry_after("") is None
    assert parse_retry_after(None) is None
    assert parse_retry_after("soon") is None


def test_parse_retry_after_http_date():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    val = format_datetime(now + timedelta(seconds=30), usegmt=True)
    assert parse_retry_after(val, now=now.timestamp()) == pytest.approx(30, abs=1)
    past = format_datetime(now - timedelta(seconds=30), usegmt=True)
    assert parse_retry_after(past, now=now.timestamp()) == 0
