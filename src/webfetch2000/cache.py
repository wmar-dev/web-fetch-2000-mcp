"""Shared result cache: HTTP-validator aware, bounded, LRU-evicted."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from collections.abc import Mapping
from dataclasses import dataclass

from .config import Settings
from .models import Fetched
from .store import Store

_MAX_AGE = re.compile(r"max-age\s*=\s*(\d+)", re.I)


def ttl_for(cache_control: str | None, has_validators: bool, settings: Settings) -> int | None:
    """Seconds an entry stays fresh, or None when it must not be stored."""
    ttl = settings.cache_ttl_s
    if settings.respect_cache_control and cache_control:
        cc = cache_control.lower()
        if "no-store" in cc:
            return None
        m = _MAX_AGE.search(cc)
        if "no-cache" in cc:
            ttl = 0
        elif m:
            ttl = int(m.group(1))
    if ttl == 0 and not has_validators:
        return None
    return ttl


@dataclass
class CacheEntry:
    key: str
    url: str
    domain: str
    final_url: str
    status: int
    content_type: str
    markdown: str
    raw: bytes
    raw_truncated: bool
    raw_total_bytes: int | None
    etag: str | None
    last_modified: str | None
    fetched_at: float
    expires_at: float
    strategy_used: str
    markdown_source: str | None
    origin_tokens: int | None
    content_signals: str | None

    def to_fetched(self) -> Fetched:
        kind = (
            "binary"
            if self.markdown_source is None
            else ("markdown" if self.markdown_source == "origin" else "html")
        )
        return Fetched(
            final_url=self.final_url,
            status=self.status,
            content_type=self.content_type,
            markdown=self.markdown,
            kind=kind,
            raw=self.raw,
            raw_truncated=self.raw_truncated,
            total_bytes=self.raw_total_bytes,
            strategy_used=self.strategy_used,
            attempts=[],
            origin_tokens=self.origin_tokens,
            content_signals=self.content_signals,
            etag=self.etag,
            last_modified=self.last_modified,
        )

    @property
    def validators(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.etag:
            out["If-None-Match"] = self.etag
        if self.last_modified:
            out["If-Modified-Since"] = self.last_modified
        return out


_COLUMNS = (
    "key, url, domain, final_url, status, content_type, body_markdown, body_raw, raw_truncated, "
    "raw_total_bytes, etag, last_modified, fetched_at, expires_at, strategy_used, "
    "markdown_source, origin_tokens, content_signals"
)


class Cache:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    @staticmethod
    def key(normalized_url: str, negotiate_markdown: bool) -> str:
        return hashlib.sha256(
            f"{normalized_url}|neg={int(negotiate_markdown)}".encode()
        ).hexdigest()

    def get(self, key: str, now: float | None = None) -> tuple[CacheEntry | None, str]:
        """Return (entry, state) with state 'fresh', 'stale' (has validators) or 'miss'."""
        now = time.time() if now is None else now
        with self.store.conn() as c:
            row = c.execute(f"SELECT {_COLUMNS} FROM cache WHERE key=?", (key,)).fetchone()
            if row is None:
                return None, "miss"
            entry = CacheEntry(
                key=row[0],
                url=row[1],
                domain=row[2],
                final_url=row[3],
                status=row[4],
                content_type=row[5],
                markdown=row[6],
                raw=bytes(row[7] or b""),
                raw_truncated=bool(row[8]),
                raw_total_bytes=row[9],
                etag=row[10],
                last_modified=row[11],
                fetched_at=row[12],
                expires_at=row[13],
                strategy_used=row[14],
                markdown_source=row[15],
                origin_tokens=row[16],
                content_signals=row[17],
            )
            if entry.expires_at > now:
                c.execute("UPDATE cache SET last_accessed_at=? WHERE key=?", (now, key))
                return entry, "fresh"
            if entry.etag or entry.last_modified:
                return entry, "stale"
            c.execute("DELETE FROM cache WHERE key=?", (key,))
            return None, "miss"

    def put(self, key: str, url: str, domain: str, f: Fetched, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        ttl = ttl_for(f.cache_control, bool(f.etag or f.last_modified), self.settings)
        if ttl is None:
            return False
        size = len(f.markdown.encode("utf-8")) + len(f.raw) + 512
        with self.store.tx() as c:
            c.execute(
                f"INSERT OR REPLACE INTO cache ({_COLUMNS}, size_bytes, last_accessed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    url,
                    domain,
                    f.final_url,
                    f.status,
                    f.content_type,
                    f.markdown,
                    f.raw,
                    int(f.raw_truncated),
                    f.total_bytes,
                    f.etag,
                    f.last_modified,
                    now,
                    now + ttl,
                    f.strategy_used,
                    f.markdown_source,
                    f.origin_tokens,
                    f.content_signals,
                    size,
                    now,
                ),
            )
            self._evict(c)
        return True

    def _evict(self, c: sqlite3.Connection) -> None:
        cap = self.settings.cache_max_mb * 1024 * 1024
        total = c.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM cache").fetchone()[0]
        while total > cap:
            row = c.execute(
                "SELECT key, size_bytes FROM cache ORDER BY last_accessed_at ASC LIMIT 1"
            ).fetchone()
            if row is None:
                break
            c.execute("DELETE FROM cache WHERE key=?", (row[0],))
            total -= row[1]

    def touch(self, key: str, headers: Mapping[str, str], now: float | None = None) -> None:
        """A 304 confirmed the entry: extend its freshness."""
        now = time.time() if now is None else now
        ttl = ttl_for(headers.get("cache-control"), True, self.settings)
        ttl = self.settings.cache_ttl_s if ttl is None else ttl
        with self.store.tx() as c:
            c.execute(
                "UPDATE cache SET expires_at=?, fetched_at=?, last_accessed_at=? WHERE key=?",
                (now + ttl, now, now, key),
            )

    def clear(self, url: str | None = None, domain: str | None = None) -> int:
        with self.store.tx() as c:
            if url is not None:
                n = c.execute("DELETE FROM cache WHERE url=?", (url,)).rowcount
            elif domain is not None:
                n = c.execute("DELETE FROM cache WHERE domain=?", (domain,)).rowcount
            else:
                n = c.execute("DELETE FROM cache").rowcount
        return int(n)

    def total_bytes(self) -> int:
        with self.store.conn() as c:
            return int(c.execute("SELECT COALESCE(SUM(size_bytes), 0) FROM cache").fetchone()[0])
