"""Shared Playwright page-fetching logic for the Chromium and Camoufox strategies."""

from __future__ import annotations

import asyncio
import contextlib
import time
from abc import abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from ..config import Settings
from ..convert import is_html_type
from ..logging import get_logger
from ..models import FetchError
from ..ratelimit import DomainLimiter, RateLimitTimeout
from ..safety import ensure_allowed
from .base import FetchOutcome, Strategy, StrategyError, StrategyRequest

log = get_logger("browser")

_CONNECT_MARKERS = (
    "ERR_NAME_NOT_RESOLVED",
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_INTERNET_DISCONNECTED",
    "ERR_ADDRESS_UNREACHABLE",
    "NS_ERROR_CONNECTION_REFUSED",
    "NS_ERROR_UNKNOWN_HOST",
    "NS_ERROR_NET_RESET",
    "NS_ERROR_NET_ON_RESOLVED",
)
_CRASH_MARKERS = (
    "Target closed",
    "Target page, context or browser has been closed",
    "Browser closed",
    "browser has been closed",
    "Connection closed",
)


@dataclass
class BrowserHandle:
    browser: Any
    close: Callable[[], Awaitable[None]]


class _Guard:
    """Request interception: SSRF checks, resource blocking and per-domain limits."""

    def __init__(
        self,
        strategy: PlaywrightStrategy,
        page_getter: Callable[[], Any],
        start_host: str,
        deadline: float,
    ) -> None:
        self.s = strategy
        self.page_getter = page_getter
        self.start_host = start_host
        self.deadline = deadline
        self.blocked: FetchError | None = None
        self._host_ok: dict[str, FetchError | None] = {}

    async def _check(self, url: str) -> FetchError | None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return None  # data:, blob:, about: never touch the network
        host = (parts.hostname or "").lower()
        if host not in self._host_ok:
            try:
                await ensure_allowed(url, self.s.settings)
                self._host_ok[host] = None
            except FetchError as e:
                self._host_ok[host] = e
        return self._host_ok[host]

    async def handle(self, route: Any, request: Any) -> None:
        try:
            if request.resource_type in self.s.settings.block_resources:
                await route.abort()
                return
            err = await self._check(request.url)
            is_main_nav = (
                request.is_navigation_request() and request.frame == self.page_getter().main_frame
            )
            if err is not None:
                if is_main_nav and self.blocked is None:
                    self.blocked = err
                await route.abort()
                return
            host = (urlsplit(request.url).hostname or "").lower()
            if is_main_nav and host and host != self.start_host and self.s.limiter is not None:
                domain = host[4:] if host.startswith("www.") else host
                remaining = max(0.0, self.deadline - time.monotonic())
                try:
                    await self.s.limiter.token(domain, remaining)
                except RateLimitTimeout as e:
                    if self.blocked is None:
                        self.blocked = FetchError("rate_limited", str(e))
                    await route.abort()
                    return
            await route.continue_()
        except Exception:  # route already handled / page closed mid-flight
            with contextlib.suppress(Exception):
                await route.abort()


class PlaywrightStrategy(Strategy):
    def __init__(
        self,
        settings: Settings,
        limiter: DomainLimiter | None,
        *,
        pages: int,
        headless_default: bool,
    ) -> None:
        self.settings = settings
        self.limiter = limiter
        self._sem = asyncio.Semaphore(pages)
        self._headless_default = headless_default
        self._handles: dict[bool, BrowserHandle] = {}
        self._locks: dict[bool, asyncio.Lock] = {}
        self._reaper: asyncio.Task[None] | None = None
        self._last_used = time.monotonic()
        self._avail: tuple[bool, str | None] | None = None
        self.open_pages = 0

    @property
    def browser_count(self) -> int:
        return len(self._handles)

    # -- subclass hooks -------------------------------------------------
    @abstractmethod
    async def _probe(self) -> tuple[bool, str | None]: ...

    @abstractmethod
    async def _launch(self, headless: bool) -> BrowserHandle: ...

    def _context_kwargs(self) -> dict[str, Any]:
        # never save downloads to disk, and keep service workers from outliving the fetch
        return {"accept_downloads": False, "service_workers": "block"}

    # -- lifecycle ------------------------------------------------------
    async def available(self) -> tuple[bool, str | None]:
        if self._avail is None:
            try:
                self._avail = await self._probe()
            except Exception as e:  # probing must never crash the server
                self._avail = (False, f"probe_failed: {e}")
        return self._avail

    async def _get_browser(self, headless: bool) -> BrowserHandle:
        lock = self._locks.setdefault(headless, asyncio.Lock())
        async with lock:
            h = self._handles.get(headless)
            if h is not None and not h.browser.is_connected():
                await self._discard(headless)
                h = None
            if h is None:
                try:
                    h = await self._launch(headless)
                except Exception as e:
                    raise StrategyError("browser_launch_failed", str(e)[:300]) from e
                self._handles[headless] = h
                log.info("browser launched", extra={"strategy": self.name, "headless": headless})
            if self._reaper is None or self._reaper.done():
                self._reaper = asyncio.create_task(self._reap_loop())
            return h

    async def _discard(self, headless: bool) -> None:
        h = self._handles.pop(headless, None)
        if h is not None:
            with contextlib.suppress(Exception):
                await h.close()

    async def _reap_loop(self) -> None:
        idle = self.settings.browser_idle_shutdown_s
        interval = max(0.25, min(5.0, idle / 2))
        while True:
            await asyncio.sleep(interval)
            if (
                self._handles
                and self.open_pages == 0
                and time.monotonic() - self._last_used >= idle
            ):
                log.info("closing idle browsers", extra={"strategy": self.name})
                await self._close_browsers()

    async def _close_browsers(self) -> None:
        for headless in list(self._handles):
            await self._discard(headless)

    async def close(self) -> None:
        reaper, self._reaper = self._reaper, None
        if reaper is not None and reaper is not asyncio.current_task():
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reaper
        await self._close_browsers()

    # -- fetching -------------------------------------------------------
    async def fetch(self, req: StrategyRequest) -> FetchOutcome:
        started = time.monotonic()
        ok, why = await self.available()
        if not ok:
            raise StrategyError(why or "unavailable")
        parsed = await ensure_allowed(req.url, self.settings)
        headless = self._headless_default and not req.headed
        deadline = started + req.timeout_s
        waited_ms = 0.0
        slot_cm: Any = (
            self.limiter.slot(parsed.domain, req.timeout_s)
            if self.limiter is not None
            else contextlib.nullcontext(None)
        )
        try:
            async with self._sem, slot_cm as slot:
                if slot is not None:
                    waited_ms = slot.waited_ms
                outcome = await self._fetch_page(req, parsed.host, headless, deadline)
        except RateLimitTimeout as e:
            raise FetchError("rate_limited", str(e)) from e
        outcome.waited_ms = waited_ms
        outcome.duration_ms = int((time.monotonic() - started) * 1000)
        return outcome

    async def _fetch_page(
        self, req: StrategyRequest, start_host: str, headless: bool, deadline: float
    ) -> FetchOutcome:
        from playwright.async_api import Error as PWError
        from playwright.async_api import TimeoutError as PWTimeout

        handle = await self._get_browser(headless)
        self.open_pages += 1
        ctx = None
        try:
            ctx = await handle.browser.new_context(**self._context_kwargs())
            page = await ctx.new_page()
            guard = _Guard(self, lambda: page, start_host, deadline)
            await ctx.route("**/*", guard.handle)
            timeout_ms = max(1000, int((deadline - time.monotonic()) * 1000))
            try:
                response = await page.goto(
                    req.url, wait_until="domcontentloaded", timeout=timeout_ms
                )
                with contextlib.suppress(PWTimeout):
                    await page.wait_for_load_state("networkidle", timeout=min(4000, timeout_ms))
            except PWTimeout as e:
                if guard.blocked:
                    raise guard.blocked from e
                raise StrategyError("timeout", f"timed out after {req.timeout_s}s") from e
            except PWError as e:
                if guard.blocked:
                    raise guard.blocked from e
                raise self._map_error(e, handle) from e
            if guard.blocked:
                raise guard.blocked
            if response is None:
                raise StrategyError("no_response", "navigation produced no response")
            headers = {k.lower(): v for k, v in response.headers.items()}
            ctype = headers.get("content-type", "")
            if not ctype or is_html_type(ctype):
                body = (await page.content()).encode("utf-8")
                ctype = "text/html; charset=utf-8"
            else:
                body = await response.body()
            total = len(body)
            truncated = total > req.max_bytes
            return FetchOutcome(
                status=response.status,
                final_url=page.url,
                headers=headers,
                body=body[: req.max_bytes],
                content_type=ctype,
                body_truncated=truncated,
                total_bytes=total,
            )
        finally:
            self.open_pages -= 1
            self._last_used = time.monotonic()
            if ctx is not None:
                with contextlib.suppress(Exception):
                    await ctx.close()

    def _map_error(self, e: Exception, handle: BrowserHandle) -> StrategyError:
        msg = str(e)
        if "Download is starting" in msg:
            return StrategyError("download_navigation", "URL triggers a file download")
        if any(m in msg for m in _CONNECT_MARKERS):
            return StrategyError("connect_error", msg.splitlines()[0][:200], retriable=True)
        if any(m in msg for m in _CRASH_MARKERS):
            return StrategyError("browser_crashed", msg.splitlines()[0][:200], retriable=True)
        return StrategyError("browser_error", msg.splitlines()[0][:200])
