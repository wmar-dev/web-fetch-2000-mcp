"""Per-user SQLite store shared by all server instances (strategy memory + result cache)."""

from __future__ import annotations

import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS outcomes (
    domain TEXT NOT NULL,
    path_prefix TEXT NOT NULL DEFAULT '',
    strategy TEXT NOT NULL,
    successes REAL NOT NULL DEFAULT 0,
    failures REAL NOT NULL DEFAULT 0,
    mean_duration_ms REAL NOT NULL DEFAULT 0,
    observations INTEGER NOT NULL DEFAULT 0,
    last_attempt_at REAL,
    last_success_at REAL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (domain, path_prefix, strategy)
);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    final_url TEXT NOT NULL,
    status INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    body_markdown TEXT NOT NULL,
    body_raw BLOB,
    raw_truncated INTEGER NOT NULL DEFAULT 0,
    raw_total_bytes INTEGER,
    etag TEXT,
    last_modified TEXT,
    fetched_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    size_bytes INTEGER NOT NULL,
    last_accessed_at REAL NOT NULL,
    strategy_used TEXT NOT NULL,
    markdown_source TEXT,
    origin_tokens INTEGER,
    content_signals TEXT
);
CREATE INDEX IF NOT EXISTS cache_lru ON cache (last_accessed_at);
CREATE INDEX IF NOT EXISTS cache_domain ON cache (domain);
"""

# version -> statements applied when upgrading *to* that version (after the base schema)
_MIGRATIONS: dict[int, list[str]] = {}


class StoreUnavailable(Exception):
    pass


class Store:
    def __init__(self, path: Path | None, error: str | None = None) -> None:
        self.path = path
        self.error = error

    @property
    def available(self) -> bool:
        return self.error is None and self.path is not None

    @classmethod
    def unavailable(cls, reason: str) -> Store:
        return cls(None, reason)

    @classmethod
    def open(cls, path: Path) -> Store:
        store = cls(path)
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if not path.exists():  # cached pages may be sensitive: owner-only from the start
                os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
            with store._connect() as c:
                c.executescript(_SCHEMA)
                row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
                current = int(row[0]) if row else 0
                for v in sorted(_MIGRATIONS):
                    if current < v:
                        for stmt in _MIGRATIONS[v]:
                            c.execute(stmt)
                if current != SCHEMA_VERSION:
                    c.execute(
                        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                    if not row:
                        c.execute(
                            "INSERT OR IGNORE INTO meta(key, value) VALUES ('created_at', ?)",
                            (str(time.time()),),
                        )
        except (sqlite3.Error, OSError) as e:
            return cls(None, f"store unavailable: {e}")
        return store

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
            except sqlite3.OperationalError:
                pass
        except sqlite3.Error:
            conn.close()
            raise
        return conn

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        """A short-lived autocommit connection."""
        if not self.available:
            raise StoreUnavailable(self.error or "store unavailable")
        try:
            c = self._connect()
        except sqlite3.Error as e:
            raise StoreUnavailable(str(e)) from e
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """A write transaction that serializes against other processes (BEGIN IMMEDIATE)."""
        with self.conn() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                yield c
            except BaseException:
                c.execute("ROLLBACK")
                raise
            else:
                c.execute("COMMIT")
