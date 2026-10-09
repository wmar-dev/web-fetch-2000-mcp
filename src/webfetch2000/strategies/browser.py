"""Chromium via Playwright: renders JavaScript."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import Settings
from ..ratelimit import DomainLimiter
from ._playwright import BrowserHandle, PlaywrightStrategy


class BrowserStrategy(PlaywrightStrategy):
    name = "browser"
    cost = 2

    def __init__(self, settings: Settings, limiter: DomainLimiter | None) -> None:
        super().__init__(
            settings,
            limiter,
            pages=settings.browser_pages,
            headless_default=settings.browser_headless,
        )

    async def _probe(self) -> tuple[bool, str | None]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return False, "playwright_not_installed"
        async with async_playwright() as p:
            exe = p.chromium.executable_path
        if not await asyncio.to_thread(Path(exe).exists):
            return False, "browser_not_installed (run: playwright install chromium)"
        return True, None

    async def _launch(self, headless: bool) -> BrowserHandle:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        args = ["--no-sandbox"] if self.settings.no_sandbox else []
        try:
            browser = await pw.chromium.launch(headless=headless, args=args)
        except BaseException:
            await pw.stop()
            raise

        async def close() -> None:
            try:
                await browser.close()
            finally:
                await pw.stop()

        return BrowserHandle(browser, close)
