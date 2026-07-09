"""Central response-cache provider: every adapter fetches through it (NFR-1, NFR-2).

Adapters call the module-level :func:`fetch` in place of ``httpx.get``. The
provider is **cache-first** (see design.md D4): a page that is fresh (age within
the TTL) is served straight from the local filesystem with no network access and
no politeness delay; an expired page is re-fetched (waited on, with a generous
timeout) and only falls back to the stale copy on failure — then a background
daemon thread keeps retrying to heal the cache (D8); a missing page is fetched
and, on failure, yields a result whose ``text`` is ``None`` so the caller skips
that source.

Storage (design.md D2) is one plain file per ``(manufacturer, url)`` at
``<cache_dir>/<manufacturer-slug>/<url-slug>__<hash8>.<ext>``. The file's
``mtime`` is its fetch timestamp — there is no separate metadata store. Writes go
to a ``.tmp`` sibling and are promoted with ``os.replace`` (atomic on one
volume), so a crash never leaves a half-written page and Microchip's thread pool
is safe (distinct URLs → distinct files → no lock needed).

The provider centralizes the shared User-Agent, the per-manufacturer minimum
delay, the per-site timeout, and transient-failure retries — boilerplate that
used to be copy-pasted into each of the twelve adapters.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from rf_finder.config import CacheConfig

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (seeded from the per-adapter values the provider now owns — design §Context)
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Minimum seconds between two *live* fetches to the same manufacturer. Fetching
# faster gets the client blocked/disconnected, so these mirror the adapters'
# former ``_MIN_DELAY_SECONDS`` exactly. A manufacturer not listed here (e.g.
# Microchip, whose MCP API is hit concurrently) has no minimum delay.
_MIN_DELAY_SECONDS: dict[str, float] = {
    "Mini-Circuits": 1.0,
    "3rWave": 1.0,
    "RWM": 1.0,
    "AmcomUSA": 1.5,
    "Marki Microwave": 1.5,
    "Qorvo": 2.0,
    "Guerrilla RF": 2.0,
    "VectraWave": 2.0,
    "UMS": 3.0,
    "Analog Devices": 5.0,
    "MACOM": 60.0,
}

# Per-site live-fetch timeout (seconds), inherited from each adapter's original
# ``timeout=`` so site-facing behavior is unchanged. Qorvo (~5.3 MB), MACOM, UMS
# (5 heavy pages) and Microchip (many feeds) used 60 s; every other adapter used
# 30 s (the default).
_TIMEOUT_SECONDS: dict[str, float] = {
    "Qorvo": 60.0,
    "MACOM": 60.0,
    "UMS": 60.0,
    "Microchip": 60.0,
}
_DEFAULT_TIMEOUT_SECONDS = 30.0

# Transient-failure retries (network error / timeout / 5xx) with linear backoff.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0

# How long a background revalidate lingers before the CLI stops waiting for it.
_REVALIDATE_JOIN_SECONDS = 90.0

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
# Provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FetchResult:
    """The outcome of a :meth:`ResponseCache.fetch` call.

    ``text`` is the page body (``None`` only for a missing page that could not be
    fetched). ``age_seconds`` is how old the served copy is (0 for a just-fetched
    page). ``served_stale`` is True when an expired copy was returned because the
    live re-fetch failed — the CLI surfaces this so an old snapshot is never
    silent.
    """

    text: str | None
    age_seconds: float
    served_stale: bool = False
    from_cache: bool = False


class ResponseCache:
    """Cache-first HTTP provider shared by every adapter (one instance per process)."""

    def __init__(self, config: CacheConfig) -> None:
        self._config = config
        self._cache_dir = Path(config.cache_dir)
        self._ttl_seconds = config.ttl_days * _SECONDS_PER_DAY
        # Serialize live fetches per manufacturer so the minimum delay is honored
        # even when adapters run concurrently (e.g. Microchip's thread pool).
        self._fetch_locks: dict[str, threading.Lock] = {}
        self._last_fetch_time: dict[str, float] = {}
        self._locks_guard = threading.Lock()
        # Single-flight background revalidations, keyed by cache path.
        self._revalidating: dict[str, threading.Thread] = {}
        self._revalidate_guard = threading.Lock()
        # When True (set by the `refresh` command), the fresh-serve shortcut is
        # bypassed so every fetch goes live and re-stores — a fresh cache is
        # still refreshed, not skipped.
        self._refresh_mode = False
        # Per-manufacturer record of what the current run served (oldest age +
        # whether any copy was stale), so the CLI can show a snapshot age.
        self._served: dict[str, tuple[float, bool]] = {}

    # -- public API --------------------------------------------------------

    def fetch(
        self,
        manufacturer: str,
        url: str,
        *,
        method: str = "GET",
        params=None,
        json=None,
        headers: dict | None = None,
        verify: bool = True,
        timeout: float | None = None,
    ) -> FetchResult:
        """Return one URL cache-first (design.md D4).

        Fresh copy (age ≤ TTL) → served from disk, no network, no delay. Expired
        copy → live fetch is attempted and waited on; success stores+returns the
        fresh copy, failure returns the stale copy and starts a background
        revalidate. Missing → live fetch; success stores+returns, failure returns
        a ``FetchResult`` whose ``text`` is ``None``.

        When the cache is disabled (``enabled=false``) this passes straight
        through to a live fetch with no read or write.
        """
        if not self._config.enabled:
            text = self._live_fetch(
                manufacturer, url, method=method, params=params,
                json=json, headers=headers, verify=verify, timeout=timeout,
            )
            return FetchResult(text=text, age_seconds=0.0)

        path = _cache_path(
            self._cache_dir, manufacturer, url,
            method=method, params=params, json_body=json,
        )
        age = self._age_seconds(path)

        # Fresh: serve from disk untouched (unless refresh mode forces a re-fetch).
        if age is not None and age <= self._ttl_seconds and not self._refresh_mode:
            result = FetchResult(
                text=path.read_text(encoding="utf-8"),
                age_seconds=age,
                from_cache=True,
            )
            self._record_served(manufacturer, result)
            return result

        # Expired or missing: try to get fresh, waiting for the site.
        text = self._live_fetch(
            manufacturer, url, method=method, params=params,
            json=json, headers=headers, verify=verify, timeout=timeout,
        )
        if text is not None:
            self._store(path, text)
            result = FetchResult(text=text, age_seconds=0.0)
            self._record_served(manufacturer, result)
            return result

        # Live fetch failed.
        if age is not None:
            # Expired copy exists — serve it, then heal in the background.
            self._start_revalidate(
                path, manufacturer, url,
                method=method, params=params, json=json,
                headers=headers, verify=verify, timeout=timeout,
            )
            result = FetchResult(
                text=path.read_text(encoding="utf-8"),
                age_seconds=age,
                served_stale=True,
                from_cache=True,
            )
            self._record_served(manufacturer, result)
            return result

        # Missing and unreachable — nothing to serve.
        return FetchResult(text=None, age_seconds=0.0)

    def join_revalidations(self, max_wait: float = _REVALIDATE_JOIN_SECONDS) -> None:
        """Wait (bounded) for outstanding background revalidations before exit.

        The tool is a short-lived CLI, so a daemon revalidate thread would be
        killed on exit and never update the cache. The CLI calls this after
        displaying results to let the cache heal, bounded by ``max_wait`` so a
        dead site can't keep the process alive.
        """
        with self._revalidate_guard:
            threads = list(self._revalidating.values())
        if not threads:
            return
        deadline = time.monotonic() + max_wait
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

    def set_refresh_mode(self, enabled: bool) -> None:
        """Force every subsequent fetch to go live and re-store (used by `refresh`)."""
        self._refresh_mode = enabled

    def served_summary(self, manufacturer: str) -> tuple[float | None, bool]:
        """Return ``(oldest_age_seconds, any_stale)`` served for ``manufacturer``.

        ``oldest_age_seconds`` is the age of the oldest copy handed to that
        manufacturer's adapter this run (``None`` if it only fetched live), and
        ``any_stale`` is True if any served copy was an expired fallback. The CLI
        uses this to show a snapshot age / "served-stale" marker per source.
        """
        return self._served.get(manufacturer, (None, False))

    def _record_served(self, manufacturer: str, result: FetchResult) -> None:
        """Fold one served result into the per-manufacturer snapshot summary."""
        prev_age, prev_stale = self._served.get(manufacturer, (None, False))
        age = result.age_seconds if result.from_cache else prev_age
        if prev_age is not None and age is not None:
            age = max(prev_age, age)
        self._served[manufacturer] = (age, prev_stale or result.served_stale)

    # -- staleness / storage ----------------------------------------------

    def _age_seconds(self, path: Path) -> float | None:
        """Seconds since ``path`` was written (its ``mtime``), or ``None`` if absent."""
        try:
            mtime = path.stat().st_mtime
        except FileNotFoundError:
            return None
        return max(0.0, time.time() - mtime)

    def _store(self, path: Path, text: str) -> None:
        """Write ``text`` to ``path`` atomically (``.tmp`` sibling then ``os.replace``)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)   # atomic on the same volume

    # -- live network ------------------------------------------------------

    def _manufacturer_lock(self, manufacturer: str) -> threading.Lock:
        """Get (creating on first use) the per-manufacturer live-fetch lock."""
        with self._locks_guard:
            lock = self._fetch_locks.get(manufacturer)
            if lock is None:
                lock = threading.Lock()
                self._fetch_locks[manufacturer] = lock
            return lock

    def _live_fetch(
        self,
        manufacturer: str,
        url: str,
        *,
        method: str,
        params,
        json,
        headers: dict | None,
        verify: bool,
        timeout: float | None,
    ) -> str | None:
        """Perform the actual HTTP request with delay + retries; ``None`` on failure.

        Enforces the manufacturer's minimum delay (serialized so concurrent
        adapters don't burst), retries transient failures with linear backoff,
        and returns the response text or ``None`` when every attempt fails.
        """
        import httpx  # lazy: keeps the module import cheap and cache-only paths socket-free

        request_headers = {"User-Agent": _USER_AGENT}
        if headers:
            request_headers.update(headers)
        fetch_timeout = timeout if timeout is not None else _TIMEOUT_SECONDS.get(
            manufacturer, _DEFAULT_TIMEOUT_SECONDS
        )
        min_delay = _MIN_DELAY_SECONDS.get(manufacturer, 0.0)

        def _attempt() -> str | None:
            last_exc: Exception | None = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    response = httpx.request(
                        method,
                        url,
                        params=params,
                        json=json,
                        headers=request_headers,
                        follow_redirects=True,
                        verify=verify,
                        timeout=fetch_timeout,
                    )
                    response.raise_for_status()
                    self._last_fetch_time[manufacturer] = time.time()
                    return response.text
                except httpx.HTTPError as exc:
                    last_exc = exc
                    self._last_fetch_time[manufacturer] = time.time()
                    if attempt < _MAX_ATTEMPTS:
                        _log.warning(
                            "%s fetch %s failed (attempt %d/%d): %s",
                            manufacturer, url, attempt, _MAX_ATTEMPTS, exc,
                        )
                        time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
            _log.error("%s fetch %s failed after %d attempts: %s",
                       manufacturer, url, _MAX_ATTEMPTS, last_exc)
            return None

        # Serialize (and pace) only manufacturers with a politeness delay. A
        # zero-delay source — Microchip's concurrent MCP/feed thread pool — must
        # NOT be funneled through one lock, or its parallelism is lost. Distinct
        # URLs map to distinct files with atomic writes, so no lock is needed for
        # correctness; the lock exists only to enforce the inter-fetch delay.
        if min_delay <= 0:
            return _attempt()
        with self._manufacturer_lock(manufacturer):
            self._respect_delay(manufacturer, min_delay)
            return _attempt()

    def _respect_delay(self, manufacturer: str, min_delay: float) -> None:
        """Sleep out the remainder of the manufacturer's minimum inter-fetch delay."""
        if min_delay <= 0:
            return
        last = self._last_fetch_time.get(manufacturer, 0.0)
        if last:
            elapsed = time.time() - last
            if elapsed < min_delay:
                time.sleep(min_delay - elapsed)

    # -- background revalidate --------------------------------------------

    def _start_revalidate(
        self,
        path: Path,
        manufacturer: str,
        url: str,
        *,
        method: str,
        params,
        json,
        headers: dict | None,
        verify: bool,
        timeout: float | None,
    ) -> None:
        """Kick off (or reuse) a daemon thread that retries a failed expired fetch.

        Single-flight per cache path: if a revalidate for this file is already
        running, do nothing.
        """
        key = str(path)
        with self._revalidate_guard:
            existing = self._revalidating.get(key)
            if existing is not None and existing.is_alive():
                return

            def _run() -> None:
                try:
                    text = self._live_fetch(
                        manufacturer, url, method=method, params=params,
                        json=json, headers=headers, verify=verify, timeout=timeout,
                    )
                    if text is not None:
                        self._store(path, text)
                        _log.info("Revalidated cache for %s (%s)", manufacturer, url)
                finally:
                    with self._revalidate_guard:
                        self._revalidating.pop(key, None)

            thread = threading.Thread(
                target=_run, name=f"revalidate:{_slug(manufacturer)}", daemon=True
            )
            self._revalidating[key] = thread
            thread.start()


# ---------------------------------------------------------------------------
# Module-level singleton — what adapters and the CLI actually call
# ---------------------------------------------------------------------------

_provider: ResponseCache | None = None


def configure(config: CacheConfig) -> ResponseCache:
    """Create (or replace) the process-wide provider from ``config``; return it.

    The CLI calls this once at startup. Tests call it with a ``tmp_path``-based
    config to get an isolated cache.
    """
    global _provider
    _provider = ResponseCache(config)
    return _provider


def fetch(manufacturer: str, url: str, **kwargs) -> FetchResult:
    """Adapter-facing entry point: fetch ``url`` through the configured provider.

    Raises ``RuntimeError`` if :func:`configure` has not been called yet — the
    provider must be set up before any adapter runs.
    """
    if _provider is None:
        raise RuntimeError("response cache not configured; call cache.configure(config) first")
    return _provider.fetch(manufacturer, url, **kwargs)


def join_revalidations(max_wait: float = _REVALIDATE_JOIN_SECONDS) -> None:
    """Wait (bounded) for background revalidations; no-op if unconfigured."""
    if _provider is not None:
        _provider.join_revalidations(max_wait)
