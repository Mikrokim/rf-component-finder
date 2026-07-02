"""SQLite response cache keyed by URL with TTL (NFR-1, NFR-2).

Stores raw response bodies (bytes), so both HTML category pages and PDF
datasheets are cached uniformly.  The first fetch of a URL hits the network;
repeat fetches within the TTL are served from disk — skipping both the network
round-trip and the polite rate-limit delay, which is what makes a repeated
search effectively instant.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_DEFAULT_DB_PATH = ".cache/rf_finder.db"
_DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days (cf. config.example.yaml cache.ttl_days)


class ResponseCache:
    """A tiny SQLite ``url -> bytes`` cache with per-entry expiry."""

    def __init__(
        self,
        db_path: str = _DEFAULT_DB_PATH,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False keeps it usable if a caller touches it off-thread;
        # the CLI is single-threaded so contention is not a concern.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS responses "
            "(url TEXT PRIMARY KEY, body BLOB NOT NULL, fetched_at REAL NOT NULL)"
        )
        self._conn.commit()

    def get(self, url: str) -> bytes | None:
        """Return the cached body for *url*, or None if absent or expired."""
        row = self._conn.execute(
            "SELECT body, fetched_at FROM responses WHERE url = ?", (url,)
        ).fetchone()
        if row is None:
            return None
        body, fetched_at = row
        if time.time() - fetched_at > self.ttl_seconds:
            return None
        return bytes(body)

    def set(self, url: str, body: bytes) -> None:
        """Store *body* for *url*, stamped with the current time."""
        self._conn.execute(
            "INSERT OR REPLACE INTO responses (url, body, fetched_at) VALUES (?, ?, ?)",
            (url, body, time.time()),
        )
        self._conn.commit()


_CACHE: ResponseCache | None = None


def get_cache() -> ResponseCache:
    """Return the process-wide response cache, created lazily on first use."""
    global _CACHE
    if _CACHE is None:
        _CACHE = ResponseCache()
    return _CACHE
