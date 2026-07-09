"""Tests for rf_finder/__main__.py — CLI wiring over the cache-first provider.

The interactive form and the adapter registry are stubbed so the tests exercise
only the wiring: a fresh search must not touch the network, and a refresh must
isolate a failing source and report a per-source outcome.
"""

from __future__ import annotations

import httpx
import pytest

import rf_finder.__main__ as entry
import rf_finder.cli as cli
import rf_finder.search as core
from rf_finder import cache
from rf_finder.cache import _cache_path
from rf_finder.config import CacheConfig
from rf_finder.models import Candidate, QuerySpec


class _FakeAdapter:
    """Adapter that fetches one URL through the provider and yields one candidate."""

    manufacturer = "FakeCo"
    supported_components = {"amplifier"}

    def __init__(self, url: str) -> None:
        self.url = url

    def search(self, spec):
        result = cache.fetch("FakeCo", self.url)
        if result.text is None:
            return []
        return [Candidate(
            model="X1", manufacturer="FakeCo", url=self.url,
            raw_params={}, source="table",
        )]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


# ---------------------------------------------------------------------------
# 4.5 A fresh search makes no network call
# ---------------------------------------------------------------------------


def test_fresh_search_makes_no_network_call(tmp_path, monkeypatch):
    provider = cache.configure(CacheConfig(cache_dir=tmp_path, ttl_days=30, enabled=True))
    # Warm the cache so the adapter's fetch is a fresh hit.
    provider._store(_cache_path(tmp_path, "FakeCo", "https://fake/x"), "<html/>")

    fake = _FakeAdapter("https://fake/x")
    # Replace the whole adapter loader so the real adapters never register/fetch.
    # (`_load_adapters` now lives in the shared core module `rf_finder.search`.)
    monkeypatch.setattr(core, "_load_adapters", lambda: {"FakeCo": fake})
    monkeypatch.setattr("rf_finder.form.build_form", lambda ct: object())
    monkeypatch.setattr("rf_finder.form.collect", lambda schema: QuerySpec("amplifier", []))
    monkeypatch.setattr("builtins.input", lambda *a: "")   # default component, don't show fails

    def _boom(*a, **k):
        raise AssertionError("network was touched on a fresh cache hit")

    monkeypatch.setattr(httpx, "request", _boom)

    entry.run_search(provider)   # must complete without hitting the network


# ---------------------------------------------------------------------------
# 4.5 Refresh continues past a failing source and reports each outcome
# ---------------------------------------------------------------------------


def test_refresh_continues_past_failure(tmp_path, monkeypatch, capsys):
    provider = cache.configure(CacheConfig(cache_dir=tmp_path, ttl_days=30, enabled=True))

    class _BadAdapter:
        manufacturer = "BadCo"
        supported_components = {"amplifier"}

        def search(self, spec):
            raise RuntimeError("boom")

    good = _FakeAdapter("https://fake/good")
    monkeypatch.setattr(core, "_load_adapters", lambda: {"BadCo": _BadAdapter(), "FakeCo": good})

    class _Resp:
        text = "<html/>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "request", lambda *a, **k: _Resp())

    cli.run_refresh(provider)

    out = capsys.readouterr().out
    assert "BadCo: failed" in out          # the failing source is reported…
    assert "FakeCo: refreshed" in out      # …and the run continues to the next
    assert provider._refresh_mode is False  # refresh mode reset in the finally
