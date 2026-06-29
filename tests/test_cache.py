"""Tests for the SQLite response cache (NFR-1, NFR-2)."""

from rf_finder.cache import ResponseCache


def _cache(tmp_path, ttl=3600):
    return ResponseCache(db_path=str(tmp_path / "c.db"), ttl_seconds=ttl)


class TestResponseCache:
    def test_miss_returns_none(self, tmp_path):
        c = _cache(tmp_path)
        assert c.get("http://x/page") is None

    def test_set_then_get_round_trip(self, tmp_path):
        c = _cache(tmp_path)
        c.set("http://x/page", b"<html>hi</html>")
        assert c.get("http://x/page") == b"<html>hi</html>"

    def test_overwrite_replaces_value(self, tmp_path):
        c = _cache(tmp_path)
        c.set("http://x/page", b"old")
        c.set("http://x/page", b"new")
        assert c.get("http://x/page") == b"new"

    def test_expired_entry_returns_none(self, tmp_path):
        c = _cache(tmp_path, ttl=-1)  # everything is immediately stale
        c.set("http://x/page", b"data")
        assert c.get("http://x/page") is None

    def test_binary_bodies_round_trip(self, tmp_path):
        c = _cache(tmp_path)
        pdf = b"%PDF-1.7\x00\x01\x02 binary \xff\xfe"
        c.set("http://x/ds.pdf", pdf)
        assert c.get("http://x/ds.pdf") == pdf

    def test_persists_across_instances(self, tmp_path):
        path = str(tmp_path / "c.db")
        ResponseCache(db_path=path).set("http://x/page", b"persisted")
        assert ResponseCache(db_path=path).get("http://x/page") == b"persisted"
