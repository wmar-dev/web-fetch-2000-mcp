"""Camoufox (stealth Firefox): fingerprint and automation-signal masking only."""

from __future__ import annotations

import os
import sys

from ..config import Settings
from ..ratelimit import DomainLimiter
from ._playwright import BrowserHandle, PlaywrightStrategy


class StealthStrategy(PlaywrightStrategy):
    name = "stealth"
    cost = 3

    def __init__(self, settings: Settings, limiter: DomainLimiter | None) -> None:
        super().__init__(
            settings,
            limiter,
            pages=settings.stealth_pages,
            headless_default=settings.stealth_headless,
        )

    async def _probe(self) -> tuple[bool, str | None]:
        try:
            from camoufox.pkgman import installed_verstr
        except ImportError:
            return False, "camoufox_not_installed"
        try:
            installed_verstr()
        except Exception:
            return False, "camoufox_browser_not_installed (run: python -m camoufox fetch)"
        return True, None

    async def _launch(self, headless: bool) -> BrowserHandle:
        from camoufox.async_api import AsyncCamoufox

        mode: bool | str = True
        if not headless:
            # headed needs a display; fall back to a virtual one on bare Linux hosts
            mode = (
                "virtual"
                if sys.platform.startswith("linux") and not os.environ.get("DISPLAY")
                else False
            )
        cm = AsyncCamoufox(headless=mode)
        browser = await cm.__aenter__()

        async def close() -> None:
            await cm.__aexit__(None, None, None)

        return BrowserHandle(browser, close)
