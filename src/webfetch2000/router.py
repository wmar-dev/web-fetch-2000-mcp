"""Strategy ladder: pick a starting strategy, fetch, judge usability, escalate, render."""

from __future__ import annotations

import asyncio
import base64
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .cache import Cache, CacheEntry
from .config import Settings
from .convert import (
    ConversionError,
    Converted,
    convert_body,
    decode_body,
    is_text_type,
    truncate_text,
)
from .detect import Verdict, classify
from .logging import get_logger, redact_url
from .models import Attempt, Fetched, FetchError, FetchRequest, FetchResult
from .ratelimit import DomainLimiter, RateLimitTimeout
from .safety import ParsedURL, ensure_allowed
from .store import StoreUnavailable
from .strategies.base import FetchOutcome, Strategy, StrategyError, StrategyRequest

log = get_logger("router")

LADDER = ("http", "browser", "stealth")


@dataclass
class _NotModified:
    """The server answered a conditional request with 304."""

    headers: dict[str, str]


@dataclass
class _Analysis:
    converted: Converted | None
    text_len: int
    sample: str
    error: str | None = None


def _analyze(outcome: FetchOutcome, url: str) -> _Analysis:
    """CPU-bound conversion (run in a worker thread)."""
    if outcome.status >= 400:
        return _Analysis(None, 0, decode_body(outcome.body[:20_000], outcome.content_type))
    try:
        conv = convert_body(outcome.body, outcome.content_type, url)
    except ConversionError as e:
        return _Analysis(None, 0, "", error=str(e))
    sample = ""
    if conv.kind in ("html", "markdown"):
        sample = decode_body(outcome.body[:20_000], outcome.content_type)
    return _Analysis(conv, len(conv.markdown), sample)


class Router:
    def __init__(
        self,
        settings: Settings,
        strategies: Mapping[str, Strategy],
        limiter: DomainLimiter | None = None,
        memory: Any = None,
        cache: Any = None,
        startup_warnings: list[str] | None = None,
    ) -> None:
        self.settings = settings
        self.strategies = dict(strategies)
        self.limiter = limiter
        self.memory = memory
        self.cache = cache
        self.startup_warnings = list(startup_warnings or [])
        self._inflight: dict[Any, asyncio.Task[Any]] = {}

    # ------------------------------------------------------------------ public
    async def fetch(self, req: FetchRequest) -> FetchResult:
        t0 = time.monotonic()
        settings = self.settings.with_overrides(
            timeout_s=req.timeout_s, negotiate_markdown=req.negotiate_markdown
        )
        parsed = await ensure_allowed(req.url, settings)
        warnings: list[str] = []
        key = Cache.key(parsed.url, settings.negotiate_markdown)

        entry: CacheEntry | None = None
        if self.cache is not None and req.cache == "use":
            try:
                entry, state = await asyncio.to_thread(self.cache.get, key)
            except (StoreUnavailable, sqlite3.Error) as e:
                warnings.append(f"cache unavailable: {e}")
                entry, state = None, "miss"
            if entry is not None and state == "fresh":
                log.info("cache", extra={"result": "hit", "url": redact_url(parsed.url)})
                return self._render(req, parsed, entry.to_fetched(), "hit", t0, warnings)
            if entry is not None and state != "stale":
                entry = None
        conditional = entry.validators if entry is not None else {}
        use_cache = self.cache is not None and req.cache != "bypass"

        flight = (
            parsed.url,
            settings.negotiate_markdown,
            req.headed,
            req.cache == "bypass",
            bool(conditional),
        )
        result = await self._shared(
            flight,
            lambda: self._work(parsed, req, settings, key, use_cache, conditional),
        )
        status = "bypassed" if req.cache == "bypass" else "miss"
        if isinstance(result, _NotModified):
            assert entry is not None
            fetched = entry.to_fetched()
            status = "revalidated"
            log.info("cache", extra={"result": "revalidated", "url": redact_url(parsed.url)})
        else:
            fetched = result
            if use_cache:
                log.info("cache", extra={"result": "miss", "url": redact_url(parsed.url)})
        return self._render(req, parsed, fetched, status, t0, warnings)

    async def _work(
        self,
        parsed: ParsedURL,
        req: FetchRequest,
        settings: Settings,
        key: str,
        use_cache: bool,
        conditional: dict[str, str],
    ) -> Fetched | _NotModified:
        result = await self._run_ladder(parsed, req, settings, conditional)
        if use_cache and self.cache is not None:
            try:
                if isinstance(result, _NotModified):
                    await asyncio.to_thread(self.cache.touch, key, result.headers)
                else:
                    await asyncio.to_thread(self.cache.put, key, parsed.url, parsed.domain, result)
            except (StoreUnavailable, sqlite3.Error) as e:
                if isinstance(result, Fetched):
                    result.warnings.append(f"cache unavailable: {e}")
        return result

    async def _shared(self, key: Any, factory: Any) -> Any:
        """Coalesce identical in-flight work; a cancelled waiter never cancels the others."""
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(factory())
            self._inflight[key] = task

            def _done(t: asyncio.Task[Any], k: Any = key) -> None:
                if self._inflight.get(k) is t:
                    del self._inflight[k]
                if not t.cancelled():
                    t.exception()  # mark retrieved even if every waiter went away

            task.add_done_callback(_done)
        return await asyncio.shield(task)

    async def close(self) -> None:
        for t in list(self._inflight.values()):
            t.cancel()
        for s in self.strategies.values():
            try:
                await s.close()
            except Exception as e:  # keep closing the others
                log.warning("strategy close failed", extra={"strategy": s.name, "error": str(e)})

    async def strategy_status(self) -> list[dict[str, Any]]:
        out = []
        for name in LADDER:
            s = self.strategies.get(name)
            if s is None:
                continue
            enabled = name in self.settings.enabled_strategies
            ok, why = await s.available() if enabled else (False, "disabled_by_settings")
            out.append(
                {
                    "name": name,
                    "cost": s.cost,
                    "available": ok and enabled,
                    **({"reason": why} if not ok and why else {}),
                }
            )
        return out

    # ------------------------------------------------------------------ ladder
    async def _order(
        self, parsed: ParsedURL, req: FetchRequest, settings: Settings, warnings: list[str]
    ) -> list[str]:
        ladder = [n for n in LADDER if n in settings.enabled_strategies and n in self.strategies]
        if req.strategy != "auto":
            name = req.strategy
            if name not in ladder:
                raise FetchError(
                    "strategy_unavailable", f"strategy '{name}' is disabled in settings"
                )
            # forced: run it first; escalate only to more expensive strategies, if allowed
            higher = [n for n in ladder if LADDER.index(n) > LADDER.index(name)]
            return [name] + (higher if req.fallback else [])
        if self.memory is None or not ladder:
            return ladder
        try:
            plan = await asyncio.to_thread(self.memory.plan, parsed.domain, parsed.path, ladder)
        except (StoreUnavailable, sqlite3.Error) as e:
            warnings.append(f"memory unavailable: {e}")
            return ladder
        log.info(
            "plan",
            extra={
                "domain": parsed.domain,
                "start": plan.start,
                "order": plan.order,
                "scope": plan.scope or None,
                "reprobe": plan.reprobe,
                "reason": plan.reason,
            },
        )
        return plan.order

    async def _record(
        self, parsed: ParsedURL, name: str, success: bool, dur: int, warnings: list[str]
    ) -> None:
        if self.memory is None:
            return
        try:
            await asyncio.to_thread(
                self.memory.record, parsed.domain, parsed.path, name, success, dur
            )
        except (StoreUnavailable, sqlite3.Error) as e:
            msg = f"memory unavailable: {e}"
            if msg not in warnings:
                warnings.append(msg)

    async def _run_ladder(
        self,
        parsed: ParsedURL,
        req: FetchRequest,
        settings: Settings,
        conditional: dict[str, str] | None = None,
    ) -> Fetched | _NotModified:
        attempts: list[Attempt] = []
        warnings: list[str] = []
        waited = 0.0
        for name in await self._order(parsed, req, settings, warnings):
            strat = self.strategies[name]
            ok, why = await strat.available()
            if not ok:
                if req.strategy == name:  # explicitly requested: never substitute another
                    raise FetchError(
                        "strategy_unavailable",
                        f"strategy '{name}' is unavailable: {why}",
                        attempts,
                    )
                attempts.append(Attempt(strategy=name, outcome="unavailable", reason=why))
                warnings.append(f"strategy '{name}' unavailable: {why}")
                continue
            result = await self._try_strategy(
                strat, parsed, req, settings, attempts, warnings, conditional or {}
            )
            if isinstance(result, _NotModified):
                return result
            if isinstance(result, Fetched):
                result.attempts = attempts
                result.waited_ms += waited
                result.warnings = warnings + result.warnings
                return result
            waited += result
        raise FetchError(
            "all_strategies_failed",
            "no strategy returned usable content: "
            + "; ".join(f"{a.strategy}={a.reason or a.outcome}" for a in attempts),
            attempts,
        )

    async def _try_strategy(
        self,
        strat: Strategy,
        parsed: ParsedURL,
        req: FetchRequest,
        settings: Settings,
        attempts: list[Attempt],
        warnings: list[str],
        conditional: dict[str, str] | None = None,
    ) -> Fetched | _NotModified | float:
        """Run one strategy with bounded retries. Returns Fetched, or ms waited on failure."""
        waited = 0.0
        sreq = StrategyRequest(
            url=parsed.url,
            timeout_s=settings.timeout_s,
            max_bytes=settings.max_response_bytes,
            headed=req.headed,
            negotiate_markdown=settings.negotiate_markdown,
            conditional_headers=dict(conditional or {}) if strat.name == "http" else {},
        )
        for attempt in range(settings.retries + 1):
            started = time.monotonic()
            last = attempt >= settings.retries
            try:
                outcome = await asyncio.wait_for(strat.fetch(sreq), settings.timeout_s + 15)
            except FetchError:
                raise
            except RateLimitTimeout as e:
                raise FetchError("rate_limited", str(e), attempts) from e
            except StrategyError as e:
                dur = int((time.monotonic() - started) * 1000)
                if e.retriable and not last:
                    await self._sleep(settings.retry_backoff_s * (2**attempt))
                    continue
                attempts.append(
                    Attempt(strategy=strat.name, outcome="failed", reason=e.reason, duration_ms=dur)
                )
                self._log_attempt(strat.name, parsed, "failed", e.reason, dur)
                await self._record(parsed, strat.name, False, dur, warnings)
                return waited
            except TimeoutError:
                dur = int((time.monotonic() - started) * 1000)
                attempts.append(
                    Attempt(
                        strategy=strat.name, outcome="failed", reason="timeout", duration_ms=dur
                    )
                )
                self._log_attempt(strat.name, parsed, "failed", "timeout", dur)
                await self._record(parsed, strat.name, False, dur, warnings)
                return waited
            except Exception as e:  # a crashing strategy must not take the server down
                dur = int((time.monotonic() - started) * 1000)
                reason = f"error: {type(e).__name__}: {e}"[:200]
                attempts.append(
                    Attempt(strategy=strat.name, outcome="failed", reason=reason, duration_ms=dur)
                )
                self._log_attempt(strat.name, parsed, "failed", reason, dur)
                await self._record(parsed, strat.name, False, dur, warnings)
                return waited

            waited += outcome.waited_ms
            if outcome.status == 304 and sreq.conditional_headers:
                dur = int((time.monotonic() - started) * 1000)
                attempts.append(Attempt(strategy=strat.name, outcome="success", duration_ms=dur))
                self._log_attempt(strat.name, parsed, "success", "not_modified", dur)
                await self._record(parsed, strat.name, True, dur, warnings)
                return _NotModified(dict(outcome.headers))
            analysis = await asyncio.to_thread(_analyze, outcome, parsed.url)
            verdict = self._verdict(outcome, analysis, req, settings)
            dur = int((time.monotonic() - started) * 1000)

            if verdict.kind == "deferred":
                attempts.append(
                    Attempt(
                        strategy=strat.name,
                        outcome="deferred",
                        reason=verdict.reason,
                        duration_ms=dur,
                    )
                )
                if last:
                    raise FetchError(
                        "rate_limited",
                        f"{parsed.domain} kept asking us to back off ({verdict.reason})",
                        attempts,
                        retry_after_s=verdict.retry_after,
                    )
                wait = min(
                    verdict.retry_after
                    if verdict.retry_after is not None
                    else settings.retry_backoff_s * (2**attempt),
                    float(settings.max_retry_after_s),
                )
                self._log_attempt(strat.name, parsed, "deferred", verdict.reason, dur)
                waited += await self._sleep(wait)
                continue

            if verdict.kind == "failed":
                if analysis.error and outcome.body_truncated:
                    raise FetchError(
                        "too_large",
                        "response exceeded max_response_bytes and the truncated "
                        "content is unusable "
                        f"({analysis.error})",
                        attempts,
                    )
                attempts.append(
                    Attempt(
                        strategy=strat.name,
                        outcome="failed",
                        reason=verdict.reason,
                        duration_ms=dur,
                    )
                )
                self._log_attempt(strat.name, parsed, "failed", verdict.reason, dur)
                await self._record(parsed, strat.name, False, dur, warnings)
                return waited

            assert analysis.converted is not None
            if outcome.body_truncated and analysis.converted.kind == "pdf":
                raise FetchError(
                    "too_large",
                    "PDF exceeded max_response_bytes; a cut-off PDF cannot be read reliably",
                    attempts,
                )
            attempts.append(Attempt(strategy=strat.name, outcome="success", duration_ms=dur))
            self._log_attempt(strat.name, parsed, "success", None, dur)
            await self._record(parsed, strat.name, True, dur, warnings)
            return self._build_fetched(strat.name, outcome, analysis.converted, waited)
        return waited  # pragma: no cover

    def _verdict(
        self, outcome: FetchOutcome, analysis: _Analysis, req: FetchRequest, settings: Settings
    ) -> Verdict:
        if analysis.error:
            return Verdict("failed", "conversion_error")
        return classify(
            status=outcome.status,
            content_type=outcome.content_type,
            headers=outcome.headers,
            text_len=analysis.text_len,
            html_sample=analysis.sample,
            settings=settings,
            check_length=req.format != "raw",
        )

    def _build_fetched(
        self, name: str, outcome: FetchOutcome, conv: Converted, waited: float
    ) -> Fetched:
        h = outcome.headers
        tokens = h.get("x-markdown-tokens")
        warnings: list[str] = []
        signals = h.get("content-signal")
        if signals and "ai-input=no" in signals.replace(" ", ""):
            warnings.append(f"site content signal disallows AI input ({signals})")
        if outcome.body_truncated:
            warnings.append(
                f"response truncated at max_response_bytes "
                f"({self.settings.max_response_bytes} bytes)"
            )
        return Fetched(
            final_url=outcome.final_url,
            status=outcome.status,
            content_type=outcome.content_type,
            markdown=conv.markdown,
            kind=conv.kind,
            raw=outcome.body,
            raw_truncated=outcome.body_truncated,
            total_bytes=outcome.total_bytes if outcome.total_bytes else len(outcome.body),
            strategy_used=name,
            attempts=[],
            origin_tokens=int(tokens) if tokens and tokens.isdigit() else None,
            content_signals=signals,
            etag=h.get("etag"),
            last_modified=h.get("last-modified"),
            cache_control=h.get("cache-control"),
            waited_ms=waited,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ render
    def _render(
        self,
        req: FetchRequest,
        parsed: ParsedURL,
        f: Fetched,
        cache: str,
        t0: float,
        extra_warnings: list[str] | None = None,
    ) -> FetchResult:
        warnings = list(self.startup_warnings) + list(extra_warnings or []) + list(f.warnings)
        extra: dict[str, Any] = {}
        if req.format == "raw":
            raw = f.raw
            if is_text_type(f.content_type) or not f.content_type:
                content, encoding = decode_body(raw, f.content_type), "utf-8"
            else:
                content, encoding = base64.b64encode(raw).decode("ascii"), "base64"
            truncated = f.raw_truncated
            extra = {"total_bytes": f.total_bytes or len(raw)}
            fmt = "raw"
        else:
            encoding = "utf-8"
            fmt = "markdown"
            if f.kind == "binary":
                content, truncated = "", False
                extra = {"size_bytes": f.total_bytes or len(f.raw)}
            else:
                content, trunc, total = truncate_text(f.markdown, req.max_chars)
                truncated = trunc or f.raw_truncated
                extra = {"total_chars": total}
        if truncated and not any("truncated" in w for w in warnings):
            warnings.append("content truncated")
        return FetchResult(
            url=parsed.url,
            final_url=f.final_url,
            status=f.status,
            content_type=f.content_type,
            format=fmt,  # type: ignore[arg-type]
            content=content,
            content_encoding=encoding,  # type: ignore[arg-type]
            truncated=truncated,
            strategy_used=f.strategy_used,
            attempts=f.attempts,
            cache=cache,  # type: ignore[arg-type]
            markdown_source=f.markdown_source if fmt == "markdown" else None,  # type: ignore[arg-type]
            origin_tokens=f.origin_tokens,
            content_signals=f.content_signals,
            duration_ms=int((time.monotonic() - t0) * 1000),
            waited_ms=int(f.waited_ms),
            warnings=warnings,
            **extra,
        )

    # ------------------------------------------------------------------ utils
    async def _sleep(self, seconds: float) -> float:
        if seconds > 0:
            await asyncio.sleep(seconds)
        return seconds * 1000

    def _log_attempt(
        self, name: str, parsed: ParsedURL, outcome: str, reason: str | None, dur: int
    ) -> None:
        log.info(
            "attempt",
            extra={
                "strategy": name,
                "url": redact_url(parsed.url),
                "outcome": outcome,
                "reason": reason,
                "duration_ms": dur,
            },
        )
