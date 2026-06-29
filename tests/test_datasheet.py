"""Tests for the shared datasheet engine, the generic needs_datasheet / enrich on
the Adapter base, and the AmcomUSA datasheet hook."""

import pytest

from rf_finder.adapters import amcomusa
from rf_finder.adapters.amcomusa import AmcomUSAAdapter
from rf_finder.adapters.minicircuits import MiniCircuitsAdapter
from rf_finder.adapters.datasheet import parse_params
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue


# ---------------------------------------------------------------------------
# parse_params — shared, pattern-driven, tolerant to both real layouts
# ---------------------------------------------------------------------------

class TestParseParams:
    def test_value_before_unit(self):
        # AM001019SF-1H layout: "IP3 35 dBm"
        r = parse_params("P1dB 19 dBm\nNoise Figure 2.8 dB\nIP3 35 dBm\n", {"OIP3"})
        assert r["OIP3"].value == 35.0
        assert r["OIP3"].unit == "dBm"

    def test_unit_before_value(self):
        # AM07014020LN-P1 layout: "... IP3 dBm +25 ..."
        r = parse_params("P1dB +11 +13 1dB IP3 dBm +25 Input Return Loss", {"OIP3"})
        assert r["OIP3"].value == 25.0

    def test_oip3_explicit_label(self):
        assert parse_params("OIP3 32 dBm", {"OIP3"})["OIP3"].value == 32.0

    def test_decimal_value(self):
        assert parse_params("IP3 28.5 dBm", {"OIP3"})["OIP3"].value == 28.5

    def test_iip3_is_ignored(self):
        assert "OIP3" not in parse_params("IIP3 8 dBm", {"OIP3"})

    def test_word_containing_ip3_not_matched(self):
        assert "OIP3" not in parse_params("MYCHIP3 thing", {"OIP3"})

    def test_absent_returns_empty(self):
        assert parse_params("P1dB 19 dBm\nNoise Figure 2.8 dB", {"OIP3"}) == {}

    def test_only_wanted_params_extracted(self):
        # OIP3 present in the text but not requested -> not returned
        assert parse_params("IP3 35 dBm", set()) == {}
        # name requested but not in the pattern library -> skipped
        assert parse_params("IP3 35 dBm", {"NF"}) == {}


# ---------------------------------------------------------------------------
# needs_datasheet — generic in base, driven by per-adapter datasheet_params
# ---------------------------------------------------------------------------

class TestNeedsDatasheet:
    def _spec(self, *names):
        cons = [
            ParamConstraint(n, "between", None, (1.0, 2.0), "dBm") for n in names
        ]
        return QuerySpec("amplifier", cons)

    def test_true_when_datasheet_param_requested(self):
        assert AmcomUSAAdapter().needs_datasheet(self._spec("OIP3")) is True

    def test_true_when_among_other_params(self):
        assert AmcomUSAAdapter().needs_datasheet(self._spec("Gain", "OIP3")) is True

    def test_false_without_datasheet_param(self):
        assert AmcomUSAAdapter().needs_datasheet(self._spec("Gain", "NF")) is False

    def test_minicircuits_never_needs(self):
        # no datasheet_params declared -> default empty -> always False
        assert MiniCircuitsAdapter().needs_datasheet(self._spec("OIP3")) is False


# ---------------------------------------------------------------------------
# enrich — generic template in base, _datasheet_text hook in the adapter
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, content: bytes):
        self.content = content


class TestEnrich:
    def _adapter(self, model=None, url=None):
        a = AmcomUSAAdapter()
        if model and url:
            a._datasheet_urls[model] = url
        return a

    def test_needed_without_datasheet_param_is_noop(self):
        a = self._adapter("M", "http://x/ds.pdf")
        c = Candidate("M", "AmcomUSA", "u", {"Gain": RawValue(20.0, "dB")}, "table")
        assert a.enrich(c, {"Gain", "P1dB"}) is c

    def test_no_url_is_noop(self):
        a = self._adapter()  # no URL captured for this model
        c = Candidate("M", "AmcomUSA", "u", {}, "table")
        assert a.enrich(c, {"OIP3"}) is c

    def test_merges_oip3_and_sets_datasheet_source(self, monkeypatch):
        a = self._adapter("M", "http://x/ds.pdf")
        monkeypatch.setattr(a, "_request", lambda url: _FakeResp(b"%PDF"))
        monkeypatch.setattr(amcomusa, "extract_pdf_text", lambda b: "IP3 35 dBm")
        c = Candidate("M", "AmcomUSA", "u", {"Gain": RawValue(20.0, "dB")}, "table")

        out = a.enrich(c, {"OIP3"})

        assert out is not c
        assert out.source == "datasheet"
        assert out.raw_params["OIP3"].value == 35.0
        assert out.raw_params["Gain"].value == 20.0  # existing table value preserved

    def test_does_not_overwrite_existing_param(self, monkeypatch):
        a = self._adapter("M", "http://x/ds.pdf")
        monkeypatch.setattr(a, "_request", lambda url: _FakeResp(b""))
        monkeypatch.setattr(amcomusa, "extract_pdf_text", lambda b: "IP3 99 dBm")
        c = Candidate("M", "AmcomUSA", "u", {"OIP3": RawValue(30.0, "dBm")}, "table")
        assert a.enrich(c, {"OIP3"}) is c  # already present → nothing added

    def test_datasheet_without_param_is_noop(self, monkeypatch):
        a = self._adapter("M", "http://x/ds.pdf")
        monkeypatch.setattr(a, "_request", lambda url: _FakeResp(b""))
        monkeypatch.setattr(amcomusa, "extract_pdf_text", lambda b: "P1dB 19 dBm")
        c = Candidate("M", "AmcomUSA", "u", {}, "table")
        assert a.enrich(c, {"OIP3"}) is c

    def test_fetch_failure_is_best_effort(self, monkeypatch):
        a = self._adapter("M", "http://x/ds.pdf")

        def boom(url):
            raise RuntimeError("network down")

        monkeypatch.setattr(a, "_request", boom)
        c = Candidate("M", "AmcomUSA", "u", {}, "table")
        assert a.enrich(c, {"OIP3"}) is c  # no crash, unchanged

    def test_base_enrich_noop_for_adapter_without_datasheet(self):
        c = Candidate("M", "Mini-Circuits", "u", {}, "table")
        assert MiniCircuitsAdapter().enrich(c, {"OIP3"}) is c


# ---------------------------------------------------------------------------
# _enrich_search_results — targeting done INSIDE the adapter's search
# ---------------------------------------------------------------------------

class TestEnrichSearchResults:
    def _spec(self):
        # Gain comes from the table; OIP3 only from the datasheet.
        return QuerySpec("amplifier", [
            ParamConstraint("Gain", "between", None, (20.0, 30.0), "dB"),
            ParamConstraint("OIP3", "between", None, (30.0, float("inf")), "dBm"),
        ])

    def test_enriches_only_candidates_the_rest_already_match(self, monkeypatch):
        a = AmcomUSAAdapter()
        enriched: list[str] = []

        def fake_enrich(cand, needed):
            enriched.append(cand.model)
            return Candidate(
                cand.model, cand.manufacturer, cand.url,
                {**cand.raw_params, "OIP3": RawValue(35.0, "dBm")}, "datasheet",
            )

        monkeypatch.setattr(a, "enrich", fake_enrich)

        gain_ok = Candidate("A", "AmcomUSA", "u", {"Gain": RawValue(25.0, "dB")}, "table")    # Gain PASS, OIP3 UNKNOWN
        gain_fail = Candidate("B", "AmcomUSA", "u", {"Gain": RawValue(10.0, "dB")}, "table")  # Gain FAIL → skip
        gain_missing = Candidate("C", "AmcomUSA", "u", {}, "table")                            # Gain UNKNOWN too → skip

        out = a._enrich_search_results(self._spec(), [gain_ok, gain_fail, gain_missing])

        assert enriched == ["A"]                       # only the otherwise-matching candidate
        assert out[0].raw_params["OIP3"].value == 35.0
        assert out[1] is gain_fail                     # untouched
        assert out[2] is gain_missing                  # untouched

    def test_noop_when_spec_has_no_datasheet_param(self, monkeypatch):
        a = AmcomUSAAdapter()
        monkeypatch.setattr(a, "enrich", lambda c, n: pytest.fail("must not enrich"))
        spec = QuerySpec("amplifier", [
            ParamConstraint("Gain", "between", None, (20.0, 30.0), "dB"),
        ])
        cands = [Candidate("A", "AmcomUSA", "u", {"Gain": RawValue(25.0, "dB")}, "table")]
        assert a._enrich_search_results(spec, cands) is cands
