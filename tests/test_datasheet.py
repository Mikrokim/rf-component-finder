"""Tests for the shared datasheet engine, the generic needs_datasheet / enrich on
the Adapter base, and the AmcomUSA datasheet hook."""

import pytest

from rf_finder.adapters import amcomusa
from rf_finder.adapters.amcomusa import AmcomUSAAdapter
from rf_finder.adapters.base import AdapterError
from rf_finder.adapters.minicircuits import MiniCircuitsAdapter
from rf_finder.adapters.datasheet import parse_params
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue


_MINI_TABLE = (
    '<table id="allPnTable"><thead><tr><th>Product</th>'
    '<th>Fmin (GHz)</th><th>Fmax (GHz)</th></tr></thead>'
    '<tbody><tr><td name="product"><a href="/product-details/x">X</a></td>'
    '<td>2</td><td>6</td></tr></tbody></table>'
)


# ---------------------------------------------------------------------------
# parse_params — shared, pattern-driven, tolerant to both real layouts
# ---------------------------------------------------------------------------

class TestParseParams:
    def test_value_before_unit(self):
        # AM001019SF-1H layout: "IP3 35 dBm"
        r = parse_params("P1dB 19 dBm\nNoise Figure 2.8 dB\nIP3 35 dBm\n", {"IP3"})
        assert r["IP3"].value == 35.0
        assert r["IP3"].unit == "dBm"

    def test_unit_before_value(self):
        # AM07014020LN-P1 layout: "... IP3 dBm +25 ..."
        r = parse_params("P1dB +11 +13 1dB IP3 dBm +25 Input Return Loss", {"IP3"})
        assert r["IP3"].value == 25.0

    def test_oip3_spelling_maps_to_ip3(self):
        # datasheet may spell it "OIP3"; canonical key is "IP3"
        assert parse_params("OIP3 32 dBm", {"IP3"})["IP3"].value == 32.0

    def test_decimal_value(self):
        assert parse_params("IP3 28.5 dBm", {"IP3"})["IP3"].value == 28.5

    def test_iip3_is_ignored(self):
        assert "IP3" not in parse_params("IIP3 8 dBm", {"IP3"})

    def test_word_containing_ip3_not_matched(self):
        assert "IP3" not in parse_params("MYCHIP3 thing", {"IP3"})

    def test_absent_returns_empty(self):
        assert parse_params("P1dB 19 dBm\nNoise Figure 2.8 dB", {"IP3"}) == {}

    def test_only_wanted_params_extracted(self):
        # IP3 present in the text but not requested -> not returned
        assert parse_params("IP3 35 dBm", set()) == {}
        # name requested but not in the pattern library -> skipped
        assert parse_params("IP3 35 dBm", {"NF"}) == {}


class TestParseMSL:
    def test_msl_with_label(self):
        r = parse_params("Moisture Sensitivity Level: 3 (per J-STD-020)", {"MSL"})
        assert r["MSL"].value == 3.0
        assert r["MSL"].unit == ""

    def test_msl_abbreviation(self):
        assert parse_params("MSL 1", {"MSL"})["MSL"].value == 1.0

    def test_msl_absent(self):
        assert parse_params("Operating Temperature -40 to +85 C", {"MSL"}) == {}

    def test_msl_jedec_letter_suffix(self):
        # JEDEC levels like "2a"/"3a" are common; the digit is what matters.
        assert parse_params("MSL 2a", {"MSL"})["MSL"].value == 2.0


class TestParseTemperature:
    def test_range_to_separator(self):
        r = parse_params("Operating Temperature: -40°C to +85°C", {"Temperature"})
        assert r["Temperature"].value == (-40.0, 85.0)
        assert r["Temperature"].unit == "degC"

    def test_range_tilde_separator(self):
        r = parse_params("Case Temperature -55 ~ +125 C", {"Temperature"})
        assert r["Temperature"].value == (-55.0, 125.0)

    def test_plain_hyphen_not_a_separator(self):
        # "-40 - +85" would be ambiguous with the negative sign; not matched.
        assert parse_params("Temperature -40 - +85 C", {"Temperature"}) == {}

    def test_unicode_minus_and_spaced_plus(self):
        # Real ADL8103 wording: Unicode minus (U+2212) and a space in "+ 125".
        r = parse_params(
            "operating temperature range: −55°C to + 125°C", {"Temperature"}
        )
        assert r["Temperature"].value == (-55.0, 125.0)

    def test_no_temperature_word_needed(self):
        # Anchored on the trailing °C, not on the word "temperature".
        r = parse_params("Operating Range −40°C to +85°C", {"Temperature"})
        assert r["Temperature"].value == (-40.0, 85.0)


class TestParseSize:
    def test_size_in_mm(self):
        r = parse_params("Package size: 4 x 4 mm", {"Size"})
        assert r["Size"].value == 4.0
        assert r["Size"].unit == "mm"

    def test_size_in_inches_keeps_unit(self):
        # unit read inline -> Verifier converts in->mm; not silently mislabelled
        r = parse_params("Body size 0.49 x 0.49 in", {"Size"})
        assert r["Size"].value == 0.49
        assert r["Size"].unit == "in"

    def test_size_without_unit_is_unknown(self):
        assert parse_params("Size 4 x 4", {"Size"}) == {}

    def test_unit_after_each_dim_with_multiplication_sign(self):
        # Real ADL8103 wording: "2 mm × 2 mm" (× sign, unit after both dims).
        r = parse_params("RoHS-compliant, 2 mm × 2 mm, 8-lead LFCSP", {"Size"})
        assert r["Size"].value == 2.0
        assert r["Size"].unit == "mm"

    def test_inch_marks_on_both_dims(self):
        # AmcomUSA real wording: 1.25" x 1.25" (inch mark after each dim).
        r = parse_params('Size: 1.25" x 1.25"', {"Size"})
        assert r["Size"].value == 1.25
        assert r["Size"].unit == "in"

    def test_three_dimensions_takes_first(self):
        r = parse_params("Package 4 x 4 x 1 mm", {"Size"})
        assert r["Size"].value == 4.0
        assert r["Size"].unit == "mm"


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
        assert AmcomUSAAdapter().needs_datasheet(self._spec("IP3")) is True

    def test_true_when_among_other_params(self):
        assert AmcomUSAAdapter().needs_datasheet(self._spec("Gain", "IP3")) is True

    def test_false_without_datasheet_param(self):
        assert AmcomUSAAdapter().needs_datasheet(self._spec("Gain", "NF")) is False

    def test_minicircuits_never_needs(self):
        # no datasheet_params declared -> default empty -> always False
        assert MiniCircuitsAdapter().needs_datasheet(self._spec("IP3")) is False


# ---------------------------------------------------------------------------
# enrich — generic template in base, _datasheet_text hook in the adapter
# ---------------------------------------------------------------------------

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
        assert a.enrich(c, {"IP3"}) is c

    def test_merges_oip3_and_sets_datasheet_source(self, monkeypatch):
        a = self._adapter("M", "http://x/ds.pdf")
        monkeypatch.setattr(a, "_get_bytes", lambda url: b"%PDF")
        monkeypatch.setattr(amcomusa, "extract_pdf_text", lambda b: "IP3 35 dBm")
        c = Candidate("M", "AmcomUSA", "u", {"Gain": RawValue(20.0, "dB")}, "table")

        out = a.enrich(c, {"IP3"})

        assert out is not c
        assert out.source == "datasheet"
        assert out.raw_params["IP3"].value == 35.0
        assert out.raw_params["Gain"].value == 20.0  # existing table value preserved

    def test_merges_range_temperature(self, monkeypatch):
        # A range (contains) datasheet param merges as a (low, high) tuple.
        a = self._adapter("M", "http://x/ds.pdf")
        monkeypatch.setattr(a, "_get_bytes", lambda url: b"%PDF")
        monkeypatch.setattr(
            amcomusa, "extract_pdf_text",
            lambda b: "Operating Temperature -40 to +85 C",
        )
        c = Candidate("M", "AmcomUSA", "u", {}, "table")

        out = a.enrich(c, {"Temperature"})

        assert out.raw_params["Temperature"].value == (-40.0, 85.0)
        assert out.source == "datasheet"

    def test_does_not_overwrite_existing_param(self, monkeypatch):
        a = self._adapter("M", "http://x/ds.pdf")
        monkeypatch.setattr(a, "_get_bytes", lambda url: b"")
        monkeypatch.setattr(amcomusa, "extract_pdf_text", lambda b: "IP3 99 dBm")
        c = Candidate("M", "AmcomUSA", "u", {"IP3": RawValue(30.0, "dBm")}, "table")
        assert a.enrich(c, {"IP3"}) is c  # already present → nothing added

    def test_datasheet_without_param_is_noop(self, monkeypatch):
        a = self._adapter("M", "http://x/ds.pdf")
        monkeypatch.setattr(a, "_get_bytes", lambda url: b"")
        monkeypatch.setattr(amcomusa, "extract_pdf_text", lambda b: "P1dB 19 dBm")
        c = Candidate("M", "AmcomUSA", "u", {}, "table")
        assert a.enrich(c, {"IP3"}) is c

    def test_fetch_failure_is_best_effort(self, monkeypatch):
        a = self._adapter("M", "http://x/ds.pdf")

        def boom(url):
            raise RuntimeError("network down")

        monkeypatch.setattr(a, "_get_bytes", boom)
        c = Candidate("M", "AmcomUSA", "u", {}, "table")
        assert a.enrich(c, {"IP3"}) is c  # no crash, unchanged

    def test_base_enrich_noop_for_adapter_without_datasheet(self):
        c = Candidate("M", "Mini-Circuits", "u", {}, "table")
        assert MiniCircuitsAdapter().enrich(c, {"IP3"}) is c


# ---------------------------------------------------------------------------
# search resilience: one failed category page must not lose the others (NFR-4)
# ---------------------------------------------------------------------------

class TestSearchResilience:
    def test_one_failed_category_does_not_abort(self, monkeypatch):
        a = AmcomUSAAdapter()

        def fake_fetch(path):
            if "gan-mmic-pas" in path:
                raise AdapterError("AmcomUSA", "transient SSL error")
            return _MINI_TABLE

        monkeypatch.setattr(a, "_fetch", fake_fetch)
        result = a.search(QuerySpec("amplifier", []))   # no datasheet → no enrichment
        assert len(result) >= 1   # other categories still returned candidates

    def test_all_categories_failed_raises(self, monkeypatch):
        a = AmcomUSAAdapter()

        def boom(path):
            raise AdapterError("AmcomUSA", "down")

        monkeypatch.setattr(a, "_fetch", boom)
        with pytest.raises(AdapterError):
            a.search(QuerySpec("amplifier", []))
