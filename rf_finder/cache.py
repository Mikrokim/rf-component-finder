"""Response-cache storage mechanism: one file per ``(manufacturer, url)`` (design.md D2).

This is the **storage half** of the cache. It knows where a response lives on
disk, how old it is (file ``mtime``), and how to read/write it atomically. It
does **not** touch the network — the HTTP service (:mod:`rf_finder.http`) owns
all fetching and uses this class to implement the cache-first policy.

Layout: ``<cache_dir>/<manufacturer-slug>/<url-slug>__<hash8>.<ext>``. The
``url-slug`` is a readable fragment and ``<hash8>`` is the first 8 hex chars of
``sha256`` over the full fetch identity (url + method + params + body), so files
are human-browsable yet collision-free (this is also how Microchip's ``POST``s
to one endpoint get distinct files). Writes go to a ``.tmp`` sibling then
``os.replace`` (atomic on one volume), so a crash never leaves a half-written
page and concurrent writers to distinct URLs never collide.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

_SECONDS_PER_DAY = 86_400.0


# ---------------------------------------------------------------------------
# Path derivation:  (manufacturer, url, method, params, body) -> cache file
# ---------------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slug(text: str, *, max_len: int = 60) -> str:
    """Lowercase, keep [a-z0-9], collapse the rest to single dashes, trim length."""
    slug = _SLUG_STRIP.sub("-", (text or "").lower()).strip("-")
    return slug[:max_len].strip("-") or "x"


def _extension(url: str) -> str:
    """Pick a readable file extension from the URL path (``.html`` when unclear)."""
    tail = url.split("?", 1)[0].rsplit("/", 1)[-1]
    if "." in tail:
        ext = tail.rsplit(".", 1)[-1].lower()
        if ext.isalnum() and 1 <= len(ext) <= 5:
            return ext
    return "html"


def _identity_hash(url: str, method: str, params, json_body) -> str:
    """First 8 hex of sha256 over the full fetch identity — the collision guard.

    ``method`` and the request body are folded in so that Microchip's several
    ``POST``s to one MCP endpoint (differing only in body) map to distinct files.
    """
    parts = [method.upper(), url, repr(params), repr(json_body)]
    digest = hashlib.sha256("\x1e".join(parts).encode("utf-8")).hexdigest()
    return digest[:8]


def _cache_path(
    cache_dir: Path,
    manufacturer: str,
    url: str,
    *,
    method: str = "GET",
    params=None,
    json_body=None,
) -> Path:
    """Resolve the cache file for one fetch: ``<dir>/<mfr>/<url-slug>__<hash8>.<ext>``.

    The slug is human-browsable; the hash makes the name collision-free (and
    body-aware for non-GET). The path is deterministic, so a later read of the
    same request finds the same file.
    """
    readable = url.split("://", 1)[-1]          # drop the scheme for the slug
    filename = f"{_slug(readable)}__{_identity_hash(url, method, params, json_body)}.{_extension(url)}"
    return cache_dir / _slug(manufacturer, max_len=40) / filename


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class ResponseCache:
    """On-disk store of fetched responses; freshness is file ``mtime`` vs the TTL.

    Pure storage — no network, no threads. The HTTP service composes one of these
    and drives the cache-first policy against it.
    """

    def __init__(self, cache_dir, ttl_days: int) -> None:
        self._cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_days * _SECONDS_PER_DAY

    def path(
        self,
        manufacturer: str,
        url: str,
        *,
        method: str = "GET",
        params=None,
        json_body=None,
    ) -> Path:
        """The deterministic cache file for one fetch identity."""
        return _cache_path(
            self._cache_dir, manufacturer, url,
            method=method, params=params, json_body=json_body,
        )

    def age_seconds(self, path: Path) -> float | None:
        """Seconds since ``path`` was written (its ``mtime``), or ``None`` if absent."""
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return None
        return max(0.0, time.time() - mtime)

    def is_fresh(self, path: Path) -> bool:
        """True if ``path`` exists and is within the TTL."""
        age = self.age_seconds(path)
        return age is not None and age <= self.ttl_seconds

    def read(self, path: Path) -> str:
        """Return the stored body."""
        return Path(path).read_text(encoding="utf-8")

    def store(self, path: Path, text: str) -> None:
        """Write ``text`` to ``path`` atomically (``.tmp`` sibling then ``os.replace``)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)   # atomic on the same volume
