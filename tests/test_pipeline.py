"""Tests for the management layer (``rf_finder.pipeline``).

The end-to-end gate behaviour is covered by the §8 tests; this file pins the
resilience contract (D6): a failure that belongs to ONE candidate must never
abort the whole run.
"""

from __future__ import annotations

import rf_finder.pipeline as pipeline
from rf_finder.models import Candidate, QuerySpec, VerifiedCandidate


def _cand(model: str) -> Candidate:
    return Candidate(
        model=model, manufacturer="X", url=f"u/{model}", raw_params={}, source="table"
    )


class _FakeAdapter:
    manufacturer = "FakeCo"
    supported_components = {"amplifier"}

    def __init__(self, *candidates: Candidate) -> None:
        self._candidates = list(candidates)

    def search(self, spec):
        return self._candidates


def test_a_candidate_whose_verification_raises_does_not_abort_the_run(monkeypatch):
    """D6: verify() raising for one candidate must not lose the others.

    A real trigger is a value/unit pair the ontology cannot convert, which makes
    ``to_canonical`` raise ``ValueError`` out of ``verify()``.
    """
    spec = QuerySpec("amplifier", [])
    monkeypatch.setattr(
        pipeline, "_sources_for",
        lambda s: [_FakeAdapter(_cand("ok1"), _cand("boom"), _cand("ok2"))],
    )

    def _verify(spec, cand):
        if cand.model == "boom":
            raise ValueError("Unsupported canonical unit 'degC'")
        return VerifiedCandidate(
            candidate=cand, verdicts=[], overall="match", confidence="table"
        )

    monkeypatch.setattr(pipeline, "verify", _verify)

    out = pipeline.run_pipeline(spec)

    assert [v.candidate.model for v in out] == ["ok1", "ok2"]
