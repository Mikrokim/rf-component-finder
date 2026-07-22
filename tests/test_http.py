"""Tests for rf_finder/http.py — the cache-first HTTP service.

Network is never touched: ``httpx.request`` is replaced with a stub that records
each call and returns a canned body or raises, so we can assert *whether* a fetch
happened (fresh hits must not) and drive expired/missing/retry/revalidate paths
deterministically. ``time.sleep`` is stubbed out so delay/backoff logic runs
instantly. Storage lives in ``rf_finder.cache``; the service composes it.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

from rf_finder.cache import _cache_path
from rf_finder.config import CacheConfig
from rf_finder.http import HttpService


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
def service(tmp_path):
    """An isolated HTTP service rooted at ``tmp_path`` (30-day TTL, enabled)."""
    return HttpService(CacheConfig(cache_dir=tmp_path, ttl_days=30, enabled=True))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make delay/backoff instant and record the requested durations."""
    slept: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: slept.append(s))
    return slept


def _warm(service, manufacturer, url, text):
    """Store ``text`` as the cached copy for a URL (via the service's cache)."""
    service._cache.store(_cache_path(service._cache._cache_dir, manufacturer, url), text)


def _backdate(path, *, days: float) -> None:
    """Set a cache file's mtime ``days`` into the past (age it past/under the TTL)."""
    past = time.time() - days * 86_400.0
    os.utime(path, (past, past))


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_miss_then_hit_returns_same_content(self, service, monkeypatch):
        stub = _make_stub(("ok", "<html>page</html>"))
        monkeypatch.setattr(httpx, "request", stub)

        first = service.fetch("Qorvo", "https://q/products")
        assert first.text == "<html>page</html>"
        assert first.from_cache is False        # served from the live fetch

        second = service.fetch("Qorvo", "https://q/products")
        assert second.text == "<html>page</html>"
        assert second.from_cache is True        # now served from disk
        assert len(stub.calls) == 1             # no second network call

    def test_distinct_urls_coexist(self, service, monkeypatch):
        stub = _make_stub(("ok", "A"), ("ok", "B"))
        monkeypatch.setattr(httpx, "request", stub)

        a = service.fetch("Qorvo", "https://q/a")
        b = service.fetch("Qorvo", "https://q/b")
        assert (a.text, b.text) == ("A", "B")
        assert service.fetch("Qorvo", "https://q/a").text == "A"
        assert service.fetch("Qorvo", "https://q/b").text == "B"

    def test_restore_replaces_content_and_timestamp(self, service, monkeypatch):
        path = _cache_path(service._cache._cache_dir, "Qorvo", "https://q/p")
        _warm(service, "Qorvo", "https://q/p", "old")
        _backdate(path, days=40)                # make it expired

        stub = _make_stub(("ok", "new"))
        monkeypatch.setattr(httpx, "request", stub)

        result = service.fetch("Qorvo", "https://q/p")
        assert result.text == "new"             # refetched, not the stale "old"
        assert result.from_cache is False
        assert path.read_text(encoding="utf-8") == "new"


# ---------------------------------------------------------------------------
# Fresh served from cache; expired-then-success / expired-then-failure
# ---------------------------------------------------------------------------


class TestFreshAndExpired:
    def test_fresh_served_without_network(self, service, monkeypatch):
        _warm(service, "Qorvo", "https://q/p", "cached")   # just written → fresh
        stub = _make_stub(("err",))
        monkeypatch.setattr(httpx, "request", stub)

        result = service.fetch("Qorvo", "https://q/p")
        assert result.text == "cached"
        assert result.from_cache is True
        assert result.served_stale is False
        assert stub.calls == []                 # network never touched

    def test_expired_then_success_serves_fresh(self, service, monkeypatch):
        path = _cache_path(service._cache._cache_dir, "Qorvo", "https://q/p")
        _warm(service, "Qorvo", "https://q/p", "old")
        _backdate(path, days=40)
        stub = _make_stub(("ok", "fresh"))
        monkeypatch.setattr(httpx, "request", stub)

        result = service.fetch("Qorvo", "https://q/p")
        assert result.text == "fresh"
        assert result.served_stale is False
        assert len(stub.calls) == 1

    def test_expired_then_failure_serves_stale(self, service, monkeypatch):
        path = _cache_path(service._cache._cache_dir, "Qorvo", "https://q/p")
        _warm(service, "Qorvo", "https://q/p", "old")
        _backdate(path, days=40)
        stub = _make_stub(("err",))             # every live attempt fails
        monkeypatch.setattr(httpx, "request", stub)

        result = service.fetch("Qorvo", "https://q/p")
        assert result.text == "old"             # the stale copy
        assert result.served_stale is True
        assert result.from_cache is True
        service.join_revalidations(max_wait=5)  # let the background thread settle


# ---------------------------------------------------------------------------
# Missing-then-success / missing-then-failure
# ---------------------------------------------------------------------------


class TestMissing:
    def test_missing_then_success_stores_and_returns(self, service, monkeypatch):
        stub = _make_stub(("ok", "body"))
        monkeypatch.setattr(httpx, "request", stub)

        result = service.fetch("Qorvo", "https://q/new")
        assert result.text == "body"
        path = _cache_path(service._cache._cache_dir, "Qorvo", "https://q/new")
        assert path.read_text(encoding="utf-8") == "body"

    def test_missing_then_failure_returns_none(self, service, monkeypatch):
        stub = _make_stub(("err",))
        monkeypatch.setattr(httpx, "request", stub)

        result = service.fetch("Qorvo", "https://q/gone")
        assert result.text is None
        assert result.served_stale is False


# ---------------------------------------------------------------------------
# Per-manufacturer delay
# ---------------------------------------------------------------------------


class TestDelay:
    def test_delay_enforced_between_live_fetches(self, service, monkeypatch, _no_sleep):
        stub = _make_stub(("ok", "x"))
        monkeypatch.setattr(httpx, "request", stub)

        service.fetch("MACOM", "https://m/a")   # first: no prior timestamp, no wait
        service.fetch("MACOM", "https://m/b")   # second: must wait ~60 s
        assert any(s > 0 for s in _no_sleep)    # a positive delay was requested

    def test_no_delay_on_fresh_hit(self, service, monkeypatch, _no_sleep):
        _warm(service, "MACOM", "https://m/a", "cached")
        stub = _make_stub(("err",))
        monkeypatch.setattr(httpx, "request", stub)

        service.fetch("MACOM", "https://m/a")   # fresh → no live fetch at all
        assert _no_sleep == []                  # no delay slept


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def test_transient_failure_then_success(service, monkeypatch):
    stub = _make_stub(("err",), ("ok", "recovered"))
    monkeypatch.setattr(httpx, "request", stub)

    result = service.fetch("Qorvo", "https://q/flaky")
    assert result.text == "recovered"           # error was retried, not surfaced
    assert len(stub.calls) == 2


# ---------------------------------------------------------------------------
# Disabled cache passes through
# ---------------------------------------------------------------------------


def test_disabled_cache_passes_through(tmp_path, monkeypatch):
    service = HttpService(CacheConfig(cache_dir=tmp_path, ttl_days=30, enabled=False))
    stub = _make_stub(("ok", "live"))
    monkeypatch.setattr(httpx, "request", stub)

    result = service.fetch("Qorvo", "https://q/p")
    assert result.text == "live"
    assert len(stub.calls) == 1
    assert list(tmp_path.rglob("*.html")) == []  # nothing was written to disk


# ---------------------------------------------------------------------------
# Background revalidate after a stale fallback
# ---------------------------------------------------------------------------


class TestRevalidate:
    def test_stale_fallback_heals_in_background(self, service, monkeypatch):
        path = _cache_path(service._cache._cache_dir, "Qorvo", "https://q/p")
        _warm(service, "Qorvo", "https://q/p", "old")
        _backdate(path, days=40)
        # Foreground expired fetch exhausts its 3 attempts → serve stale +
        # revalidate; the background attempt then succeeds and heals the file.
        stub = _make_stub(("err",), ("err",), ("err",), ("ok", "healed"))
        monkeypatch.setattr(httpx, "request", stub)

        result = service.fetch("Qorvo", "https://q/p")
        assert result.served_stale is True
        service.join_revalidations(max_wait=5)
        assert path.read_text(encoding="utf-8") == "healed"

    def test_fresh_hit_starts_no_revalidate(self, service, monkeypatch):
        _warm(service, "Qorvo", "https://q/p", "cached")   # fresh
        stub = _make_stub(("ok", "unused"))
        monkeypatch.setattr(httpx, "request", stub)

        service.fetch("Qorvo", "https://q/p")
        assert service._revalidating == {}      # no background thread registered
