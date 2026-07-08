"""Tests for rf_finder/cache.py — the cache-first response provider.

Network is never touched: ``httpx.request`` is replaced with a stub that records
each call and returns a canned body or raises, so we can assert *whether* a fetch
happened (fresh hits must not) and drive expired/missing/retry/revalidate paths
deterministically. ``time.sleep`` is stubbed out so delay/backoff logic runs
instantly.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

from rf_finder.cache import ResponseCache, _cache_path
from rf_finder.config import CacheConfig


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:  # always 2xx in the stub
        pass


def _make_stub(*behaviors):
    """Build a fake ``httpx.request``.

    Each behavior is ``("ok", text)`` or ``("err",)``, consumed one per call;
    once exhausted the last behavior repeats. The returned callable carries a
    ``.calls`` list of ``(method, url, kwargs)`` tuples.
    """

    def _request(method, url, **kwargs):
        idx = len(_request.calls)
        _request.calls.append((method, url, kwargs))
        behavior = behaviors[idx] if idx < len(behaviors) else behaviors[-1]
        if behavior[0] == "err":
            raise httpx.ConnectError("stubbed connection failure")
        return _FakeResponse(behavior[1])

    _request.calls = []
    return _request


@pytest.fixture
def cache(tmp_path):
    """An isolated cache rooted at ``tmp_path`` (30-day TTL, enabled)."""
    return ResponseCache(
        CacheConfig(cache_dir=tmp_path, ttl_days=30, enabled=True)
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make delay/backoff instant and record the requested durations."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    return slept


def _backdate(path, *, days: float) -> None:
    """Set a cache file's mtime ``days`` into the past (age it past/under the TTL)."""
    past = time.time() - days * 86_400.0
    os.utime(path, (past, past))


# ---------------------------------------------------------------------------
# 3.1 Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_miss_then_hit_returns_same_content(self, cache, monkeypatch):
        stub = _make_stub(("ok", "<html>page</html>"))
        monkeypatch.setattr(httpx, "request", stub)

        first = cache.fetch("Qorvo", "https://q/products")
        assert first.text == "<html>page</html>"
        assert first.from_cache is False        # served from the live fetch

        second = cache.fetch("Qorvo", "https://q/products")
        assert second.text == "<html>page</html>"
        assert second.from_cache is True        # now served from disk
        assert len(stub.calls) == 1             # no second network call

    def test_distinct_urls_coexist(self, cache, monkeypatch):
        stub = _make_stub(("ok", "A"), ("ok", "B"))
        monkeypatch.setattr(httpx, "request", stub)

        a = cache.fetch("Qorvo", "https://q/a")
        b = cache.fetch("Qorvo", "https://q/b")
        assert (a.text, b.text) == ("A", "B")
        assert cache.fetch("Qorvo", "https://q/a").text == "A"
        assert cache.fetch("Qorvo", "https://q/b").text == "B"

    def test_restore_replaces_content_and_timestamp(self, cache, monkeypatch):
        path = _cache_path(cache._cache_dir, "Qorvo", "https://q/p")
        cache._store(path, "old")
        _backdate(path, days=40)                # make it expired

        stub = _make_stub(("ok", "new"))
        monkeypatch.setattr(httpx, "request", stub)

        result = cache.fetch("Qorvo", "https://q/p")
        assert result.text == "new"             # refetched, not the stale "old"
        assert result.from_cache is False
        assert path.read_text(encoding="utf-8") == "new"


# ---------------------------------------------------------------------------
# 3.2 Non-GET filenames
# ---------------------------------------------------------------------------


def test_post_bodies_map_to_distinct_files(tmp_path):
    url = "https://microchip/mcp"
    p1 = _cache_path(tmp_path, "Microchip", url, method="POST", json_body={"q": 1})
    p2 = _cache_path(tmp_path, "Microchip", url, method="POST", json_body={"q": 2})
    assert p1 != p2                             # body folds into the hash

    same = _cache_path(tmp_path, "Microchip", url, method="POST", json_body={"q": 1})
    assert p1 == same                           # deterministic for the same identity


# ---------------------------------------------------------------------------
# 3.3 Fresh served from cache; expired-then-success / expired-then-failure
# ---------------------------------------------------------------------------


class TestFreshAndExpired:
    def test_fresh_served_without_network(self, cache, monkeypatch):
        path = _cache_path(cache._cache_dir, "Qorvo", "https://q/p")
        cache._store(path, "cached")            # just written → fresh
        stub = _make_stub(("err",))
        monkeypatch.setattr(httpx, "request", stub)

        result = cache.fetch("Qorvo", "https://q/p")
        assert result.text == "cached"
        assert result.from_cache is True
        assert result.served_stale is False
        assert stub.calls == []                 # network never touched

    def test_expired_then_success_serves_fresh(self, cache, monkeypatch):
        path = _cache_path(cache._cache_dir, "Qorvo", "https://q/p")
        cache._store(path, "old")
        _backdate(path, days=40)
        stub = _make_stub(("ok", "fresh"))
        monkeypatch.setattr(httpx, "request", stub)

        result = cache.fetch("Qorvo", "https://q/p")
        assert result.text == "fresh"
        assert result.served_stale is False
        assert len(stub.calls) == 1

    def test_expired_then_failure_serves_stale(self, cache, monkeypatch):
        path = _cache_path(cache._cache_dir, "Qorvo", "https://q/p")
        cache._store(path, "old")
        _backdate(path, days=40)
        stub = _make_stub(("err",))             # every live attempt fails
        monkeypatch.setattr(httpx, "request", stub)

        result = cache.fetch("Qorvo", "https://q/p")
        assert result.text == "old"             # the stale copy
        assert result.served_stale is True
        assert result.from_cache is True
        cache.join_revalidations(max_wait=5)    # let the background thread settle


# ---------------------------------------------------------------------------
# 3.4 Missing-then-success / missing-then-failure
# ---------------------------------------------------------------------------


class TestMissing:
    def test_missing_then_success_stores_and_returns(self, cache, monkeypatch):
        stub = _make_stub(("ok", "body"))
        monkeypatch.setattr(httpx, "request", stub)

        result = cache.fetch("Qorvo", "https://q/new")
        assert result.text == "body"
        path = _cache_path(cache._cache_dir, "Qorvo", "https://q/new")
        assert path.read_text(encoding="utf-8") == "body"

    def test_missing_then_failure_returns_none(self, cache, monkeypatch):
        stub = _make_stub(("err",))
        monkeypatch.setattr(httpx, "request", stub)

        result = cache.fetch("Qorvo", "https://q/gone")
        assert result.text is None
        assert result.served_stale is False


# ---------------------------------------------------------------------------
# 3.5 Per-manufacturer delay
# ---------------------------------------------------------------------------


class TestDelay:
    def test_delay_enforced_between_live_fetches(self, cache, monkeypatch, _no_sleep):
        stub = _make_stub(("ok", "x"))
        monkeypatch.setattr(httpx, "request", stub)

        cache.fetch("MACOM", "https://m/a")     # first: no prior timestamp, no wait
        cache.fetch("MACOM", "https://m/b")     # second: must wait ~60 s
        assert any(s > 0 for s in _no_sleep)    # a positive delay was requested

    def test_no_delay_on_fresh_hit(self, cache, monkeypatch, _no_sleep):
        path = _cache_path(cache._cache_dir, "MACOM", "https://m/a")
        cache._store(path, "cached")
        stub = _make_stub(("err",))
        monkeypatch.setattr(httpx, "request", stub)

        cache.fetch("MACOM", "https://m/a")     # fresh → no live fetch at all
        assert _no_sleep == []                  # no delay slept


# ---------------------------------------------------------------------------
# 3.6 Retry
# ---------------------------------------------------------------------------


def test_transient_failure_then_success(cache, monkeypatch):
    stub = _make_stub(("err",), ("ok", "recovered"))
    monkeypatch.setattr(httpx, "request", stub)

    result = cache.fetch("Qorvo", "https://q/flaky")
    assert result.text == "recovered"           # error was retried, not surfaced
    assert len(stub.calls) == 2


# ---------------------------------------------------------------------------
# 3.7 Disabled cache passes through
# ---------------------------------------------------------------------------


def test_disabled_cache_passes_through(tmp_path, monkeypatch):
    cache = ResponseCache(CacheConfig(cache_dir=tmp_path, ttl_days=30, enabled=False))
    stub = _make_stub(("ok", "live"))
    monkeypatch.setattr(httpx, "request", stub)

    result = cache.fetch("Qorvo", "https://q/p")
    assert result.text == "live"
    assert len(stub.calls) == 1
    assert list(tmp_path.rglob("*.html")) == []  # nothing was written to disk


# ---------------------------------------------------------------------------
# 3.8 Background revalidate after a stale fallback
# ---------------------------------------------------------------------------


class TestRevalidate:
    def test_stale_fallback_heals_in_background(self, cache, monkeypatch):
        path = _cache_path(cache._cache_dir, "Qorvo", "https://q/p")
        cache._store(path, "old")
        _backdate(path, days=40)
        # Foreground expired fetch exhausts its 3 attempts → serve stale +
        # revalidate; the background attempt then succeeds and heals the file.
        stub = _make_stub(("err",), ("err",), ("err",), ("ok", "healed"))
        monkeypatch.setattr(httpx, "request", stub)

        result = cache.fetch("Qorvo", "https://q/p")
        assert result.served_stale is True
        cache.join_revalidations(max_wait=5)
        assert path.read_text(encoding="utf-8") == "healed"

    def test_fresh_hit_starts_no_revalidate(self, cache, monkeypatch):
        path = _cache_path(cache._cache_dir, "Qorvo", "https://q/p")
        cache._store(path, "cached")            # fresh
        stub = _make_stub(("ok", "unused"))
        monkeypatch.setattr(httpx, "request", stub)

        cache.fetch("Qorvo", "https://q/p")
        assert cache._revalidating == {}        # no background thread registered
