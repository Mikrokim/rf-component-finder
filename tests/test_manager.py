"""Tests for the SearchManager: adapter orchestration, per-adapter error
isolation (NFR-4), and datasheet-enrichment targeting (moved out of the adapter
so the adapter no longer depends on the Verifier)."""

import pytest

from rf_finder.adapters.amcomusa import AmcomUSAAdapter
from rf_finder.adapters.base import Adapter, AdapterError
from rf_finder.manager import SearchManager
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue


# ---------------------------------------------------------------------------
# Enrichment targeting — the verify-based decision now lives in the manager.
# ---------------------------------------------------------------------------

class TestEnrichTargeting:
    def _spec(self):
        # Gain comes from the table; IP3 only from the datasheet.
        return QuerySpec("amplifier", [
            ParamConstraint("Gain", "between", None, (20.0, 30.0), "dB"),
            ParamConstraint("IP3", "between", None, (30.0, float("inf")), "dBm"),
        ])

    def test_enriches_only_candidates_the_rest_already_match(self, monkeypatch):
        a = AmcomUSAAdapter()
        enriched: list[str] = []

        def fake_enrich(cand, needed):
            enriched.append(cand.model)
            return Candidate(
                cand.model, cand.manufacturer, cand.url,
                {**cand.raw_params, "IP3": RawValue(35.0, "dBm")}, "datasheet",
            )

        monkeypatch.setattr(a, "enrich", fake_enrich)

        gain_ok = Candidate("A", "AmcomUSA", "u", {"Gain": RawValue(25.0, "dB")}, "table")    # Gain PASS, IP3 UNKNOWN
        gain_fail = Candidate("B", "AmcomUSA", "u", {"Gain": RawValue(10.0, "dB")}, "table")  # Gain FAIL → skip
        gain_missing = Candidate("C", "AmcomUSA", "u", {}, "table")                            # Gain UNKNOWN too → skip

        out = SearchManager([a])._enrich(a, self._spec(), [gain_ok, gain_fail, gain_missing])

        assert enriched == ["A"]                       # only the otherwise-matching candidate
        assert out[0].raw_params["IP3"].value == 35.0
        assert out[1] is gain_fail                     # untouched
        assert out[2] is gain_missing                  # untouched

    def test_noop_when_spec_has_no_datasheet_param(self, monkeypatch):
        a = AmcomUSAAdapter()
        monkeypatch.setattr(a, "enrich", lambda c, n: pytest.fail("must not enrich"))
        spec = QuerySpec("amplifier", [
            ParamConstraint("Gain", "between", None, (20.0, 30.0), "dB"),
        ])
        cands = [Candidate("A", "AmcomUSA", "u", {"Gain": RawValue(25.0, "dB")}, "table")]
        assert SearchManager([a])._enrich(a, spec, cands) is cands


# ---------------------------------------------------------------------------
# run() — adapter loop, verification, component filtering, error isolation.
# ---------------------------------------------------------------------------

class _FakeAdapter(Adapter):
    manufacturer = "Fake"
    supported_components = {"amplifier"}

    def __init__(self, candidates=None, error=None):
        self._candidates = candidates or []
        self._error = error

    def search(self, spec):
        if self._error is not None:
            raise self._error
        return list(self._candidates)


class TestRun:
    def test_verifies_every_candidate(self):
        c = Candidate("M", "Fake", "u", {"Gain": RawValue(25.0, "dB")}, "table")
        spec = QuerySpec("amplifier", [ParamConstraint("Gain", "min", 20.0, None, "dB")])
        verified, errors = SearchManager([_FakeAdapter([c])]).run(spec)
        assert errors == []
        assert len(verified) == 1
        assert verified[0].overall == "match"

    def test_skips_unsupported_component(self):
        class MixerOnly(_FakeAdapter):
            supported_components = {"mixer"}

        verified, errors = SearchManager([MixerOnly([])]).run(QuerySpec("amplifier", []))
        assert verified == []
        assert errors == []

    def test_adapter_error_is_isolated(self):
        bad = _FakeAdapter(error=AdapterError("Fake", "down"))
        good = _FakeAdapter([Candidate("M", "Fake", "u", {}, "table")])

        verified, errors = SearchManager([bad, good]).run(QuerySpec("amplifier", []))

        assert len(verified) == 1            # the healthy adapter still returned
        assert len(errors) == 1              # the failed one was reported, not raised
        assert "down" in errors[0]
