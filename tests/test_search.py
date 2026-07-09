"""Tests for the shared headless search core (``rf_finder.search``).

``search_and_verify`` is the one search implementation the CLI and the desktop
GUI both call, so these tests pin its contract independent of either front-end:
the match→partial→fail ordering and per-source error isolation.
"""

from __future__ import annotations

import rf_finder.search as core
import rf_finder.verifier as verifier
from rf_finder.models import Candidate, QuerySpec, VerifiedCandidate


def _cand(model: str) -> Candidate:
    return Candidate(model=model, manufacturer="X", url=f"u/{model}", raw_params={}, source="table")


class _FakeAdapter:
    manufacturer = "FakeCo"
    supported_components = {"amplifier"}

    def __init__(self, *candidates: Candidate) -> None:
        self._candidates = list(candidates)

    def search(self, spec):
        return self._candidates


def _stub_verify(monkeypatch, overall_by_model: dict[str, str]) -> None:
    """Make ``verify`` assign a chosen overall verdict per candidate model."""
    monkeypatch.setattr(
        verifier, "verify",
        lambda spec, c: VerifiedCandidate(
            candidate=c, verdicts=[], overall=overall_by_model[c.model], confidence="table"
        ),
    )


def test_search_and_verify_orders_match_partial_fail(monkeypatch):
    spec = QuerySpec("amplifier", [])
    # Deliberately discovered out of order: fail, match, partial.
    monkeypatch.setattr(
        core, "_sources_for",
        lambda s: [_FakeAdapter(_cand("f"), _cand("m"), _cand("p"))],
    )
    _stub_verify(monkeypatch, {"m": "match", "p": "partial", "f": "fail"})

    out = core.search_and_verify(spec)

    assert [v.overall for v in out] == ["match", "partial", "fail"]


def test_search_and_verify_isolates_a_failing_source(monkeypatch):
    spec = QuerySpec("amplifier", [])

    class _BadAdapter:
        manufacturer = "BadCo"
        supported_components = {"amplifier"}

        def search(self, spec):
            raise RuntimeError("boom")

    good = _FakeAdapter(_cand("m"))
    monkeypatch.setattr(core, "_sources_for", lambda s: [_BadAdapter(), good])
    _stub_verify(monkeypatch, {"m": "match"})

    events: list[str] = []
    out = core.search_and_verify(spec, on_source=lambda outcome, a, p: events.append(outcome))

    assert [v.candidate.model for v in out] == ["m"]   # the good source still returns
    assert "error" in events and "ok" in events        # both outcomes reported
