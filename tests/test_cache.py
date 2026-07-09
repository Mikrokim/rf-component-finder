"""Tests for rf_finder/cache.py — the response-cache storage mechanism.

Pure storage: path derivation, freshness by mtime vs TTL, and atomic read/write.
No network is involved (that is the HTTP service's job — see test_http.py).
"""

from __future__ import annotations

import os
import time

from rf_finder.cache import ResponseCache, _cache_path


def _backdate(path, *, days: float) -> None:
    """Set a file's mtime ``days`` into the past."""
    past = time.time() - days * 86_400.0
    os.utime(path, (past, past))


# ---------------------------------------------------------------------------
# Path derivation
# ---------------------------------------------------------------------------


class TestPath:
    def test_deterministic_and_readable(self, tmp_path):
        p = _cache_path(tmp_path, "Qorvo", "https://www.qorvo.com/products/product-list/")
        assert p == _cache_path(tmp_path, "Qorvo", "https://www.qorvo.com/products/product-list/")
        assert p.parent.name == "qorvo"          # manufacturer sub-dir
        assert p.suffix == ".html"
        assert "qorvo" in p.name                  # human-browsable slug

    def test_distinct_urls_distinct_files(self, tmp_path):
        a = _cache_path(tmp_path, "Qorvo", "https://q/a")
        b = _cache_path(tmp_path, "Qorvo", "https://q/b")
        assert a != b

    def test_post_bodies_map_to_distinct_files(self, tmp_path):
        url = "https://microchip/mcp"
        p1 = _cache_path(tmp_path, "Microchip", url, method="POST", json_body={"q": 1})
        p2 = _cache_path(tmp_path, "Microchip", url, method="POST", json_body={"q": 2})
        assert p1 != p2                           # body folds into the hash
        same = _cache_path(tmp_path, "Microchip", url, method="POST", json_body={"q": 1})
        assert p1 == same                         # deterministic for the same identity


# ---------------------------------------------------------------------------
# Store / read round-trip
# ---------------------------------------------------------------------------


class TestStoreRead:
    def test_round_trip(self, tmp_path):
        cache = ResponseCache(tmp_path, ttl_days=30)
        path = cache.path("Qorvo", "https://q/p")
        cache.store(path, "hello")
        assert cache.read(path) == "hello"

    def test_store_creates_parent_dirs(self, tmp_path):
        cache = ResponseCache(tmp_path / "nested" / "deep", ttl_days=30)
        path = cache.path("Qorvo", "https://q/p")
        cache.store(path, "x")                    # must not raise
        assert path.read_text(encoding="utf-8") == "x"

    def test_restore_replaces_content(self, tmp_path):
        cache = ResponseCache(tmp_path, ttl_days=30)
        path = cache.path("Qorvo", "https://q/p")
        cache.store(path, "old")
        cache.store(path, "new")
        assert cache.read(path) == "new"

    def test_no_tmp_file_left_behind(self, tmp_path):
        cache = ResponseCache(tmp_path, ttl_days=30)
        path = cache.path("Qorvo", "https://q/p")
        cache.store(path, "x")
        assert list(path.parent.glob("*.tmp")) == []   # atomic promote, no leftovers


# ---------------------------------------------------------------------------
# Age / freshness
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_age_none_when_absent(self, tmp_path):
        cache = ResponseCache(tmp_path, ttl_days=30)
        path = cache.path("Qorvo", "https://q/missing")
        assert cache.age_seconds(path) is None
        assert cache.is_fresh(path) is False

    def test_just_stored_is_fresh(self, tmp_path):
        cache = ResponseCache(tmp_path, ttl_days=30)
        path = cache.path("Qorvo", "https://q/p")
        cache.store(path, "x")
        assert cache.age_seconds(path) < 5
        assert cache.is_fresh(path) is True

    def test_expired_past_ttl_not_fresh(self, tmp_path):
        cache = ResponseCache(tmp_path, ttl_days=30)
        path = cache.path("Qorvo", "https://q/p")
        cache.store(path, "x")
        _backdate(path, days=40)                  # older than the 30-day TTL
        assert cache.is_fresh(path) is False
        assert cache.age_seconds(path) > 30 * 86_400.0

    def test_ttl_boundary(self, tmp_path):
        cache = ResponseCache(tmp_path, ttl_days=30)
        path = cache.path("Qorvo", "https://q/p")
        cache.store(path, "x")
        _backdate(path, days=10)                  # within a 30-day TTL
        assert cache.is_fresh(path) is True
