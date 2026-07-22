"""Offline unit tests for the Mini-Circuits adapter (T8).

All tests use the local HTML fixture — no network access required.
The ``test_search_live`` test is marked ``@pytest.mark.network`` and is
skipped in the default ``-m "not network"`` run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.minicircuits import MiniCircuitsAdapter
from rf_finder.models import Candidate, RawValue

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent.parent / "fixtures" / "minicircuits_amplifiers.html"


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def _load_candidates() -> list[Candidate]:
    adapter = MiniCircuitsAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    return adapter._parse_html(html)


# ---------------------------------------------------------------------------
# Tests from t8-plan.md §7
# ---------------------------------------------------------------------------

def test_parse_fixture_returns_candidates():
    """At least 10 candidates are parsed from the fixture."""
    candidates = _load_candidates()
    assert len(candidates) >= 10


def test_candidate_model_and_manufacturer():
    """First candidate has correct manufacturer, source, and non-empty model."""
    candidates = _load_candidates()
    c = candidates[0]
    assert c.manufacturer == "Mini-Circuits"
    assert c.source == "table"
    assert c.model  # non-empty


def test_freq_range_is_rawvalue_tuple_in_mhz():
    """ADCA3270 freq_range must be RawValue((45.0, 1218.0), 'MHz')."""
    candidates = _load_candidates()
    c = next(x for x in candidates if x.model == "ADCA3270")
    rv = c.raw_params["freq_range"]
    assert isinstance(rv, RawValue)
    assert isinstance(rv.value, tuple)
    assert rv.unit == "MHz"
    assert rv.value == (45.0, 1218.0)


def test_missing_param_is_absent_not_none():
    """Cells containing '-' must be absent from raw_params (not stored as None)."""
    candidates = _load_candidates()
    # ADCA3270 has P1dB = '-', PSAT = '-', OIP3 = '-'
    c = next(x for x in candidates if x.model == "ADCA3270")
    assert "P1dB" not in c.raw_params
    assert "Psat" not in c.raw_params
    assert "IP3" not in c.raw_params


def test_present_scalar_param():
    """ADCA3270 Gain must be RawValue(25.0, 'dB')."""
    candidates = _load_candidates()
    c = next(x for x in candidates if x.model == "ADCA3270")
    gain = c.raw_params["Gain"]
    assert gain == RawValue(value=25.0, unit="dB")


def test_candidate_url_contains_model():
    """Each candidate URL must contain the model name and 'minicircuits.com'."""
    candidates = _load_candidates()
    c = candidates[0]
    assert c.model in c.url
    assert "minicircuits.com" in c.url


def test_adapter_raises_adaptererror_on_bad_html():
    """_parse_html must raise AdapterError when table#maintable is absent."""
    from rf_finder.adapters.base import AdapterError

    adapter = MiniCircuitsAdapter()
    with pytest.raises(AdapterError):
        adapter._parse_html("<html><body>no table here</body></html>")


def test_all_params_present_row():
    """ZX60-P103LN+ has all RF params plus VDD present in raw_params."""
    candidates = _load_candidates()
    c = next(x for x in candidates if x.model == "ZX60-P103LN+")
    expected_keys = {"freq_range", "Gain", "NF", "P1dB", "Psat", "IP3", "VDD"}
    assert expected_keys <= c.raw_params.keys(), (
        f"Missing keys: {expected_keys - c.raw_params.keys()}"
    )


def test_high_freq_row():
    """HMC441LP3E is a high-frequency part (6000–20000 MHz stored in MHz)."""
    candidates = _load_candidates()
    c = next(x for x in candidates if x.model == "HMC441LP3E")
    rv = c.raw_params["freq_range"]
    assert rv.unit == "MHz"
    assert rv.value == (6000.0, 20000.0)


def test_non_parseable_current_does_not_raise():
    """Rows with '350/480' in Current cell parse without error; current not stored."""
    candidates = _load_candidates()
    # ADCA3270 has Current='350/480' and DUAL-RANGE-TEST also has it
    adca = next(x for x in candidates if x.model == "ADCA3270")
    # current is not in the ontology; key must simply be absent (not crash)
    assert "current" not in adca.raw_params


def test_adca3270_nf_present():
    """ADCA3270 NF = 3 dB is present (sanity check for a different scalar)."""
    candidates = _load_candidates()
    c = next(x for x in candidates if x.model == "ADCA3270")
    assert c.raw_params["NF"] == RawValue(value=3.0, unit="dB")


def test_vdd_parsed_from_voltage_column():
    """VDD from the 'Voltage (V)' column is stored as a degenerate (v, v) range."""
    candidates = _load_candidates()
    c = next(x for x in candidates if x.model == "ADCA3270")
    assert c.raw_params["VDD"] == RawValue(value=(24.0, 24.0), unit="V")


def test_dc_low_freq_parsed_as_zero():
    """A 'DC' low-band edge must parse as 0.0 so the part keeps its
    freq_range (GALI-39+ is DC-8000 MHz)."""
    candidates = _load_candidates()
    c = next(x for x in candidates if x.model == "GALI-39+")
    rv = c.raw_params["freq_range"]
    assert rv.unit == "MHz"
    assert rv.value == (0.0, 8000.0)


# ---------------------------------------------------------------------------
# Integration test (network, skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_search_live():
    """Live search against Mini-Circuits website (requires network)."""
    from rf_finder.models import ParamConstraint, QuerySpec

    spec = QuerySpec(
        component_type="amplifier",
        constraints=[
            ParamConstraint(
                canonical_name="freq_range",
                comparison="contains",
                value=None,
                range=(2.0, 6.0),
                unit="GHz",
            ),
        ],
    )
    adapter = MiniCircuitsAdapter()
    results = adapter.search(spec)
    assert len(results) > 0
    assert all(c.manufacturer == "Mini-Circuits" for c in results)


# ---------------------------------------------------------------------------
# Datasheet link (case 2: resolved on demand from the product page)
# ---------------------------------------------------------------------------

_PRODUCT_PAGE_HTML = """
<html><body>
  <a href="/WebStore/spec.html">Specs</a>
  <a href="https://www.minicircuits.com/pdfs/ZHL-2-S+.pdf">DATASHEET</a>
</body></html>
"""


def test_search_leaves_datasheet_url_none_and_makes_no_extra_request(monkeypatch):
    """Case 2: the amplifiers table carries no datasheet link."""
    def _boom(self, url):  # any resolve-time fetch would use _get
        raise AssertionError(f"search() must not fetch a product page: {url}")
    monkeypatch.setattr(MiniCircuitsAdapter, "_get", _boom, raising=True)
    # search() itself still needs the table; feed it the fixture directly instead.
    cands = MiniCircuitsAdapter()._parse_html(FIXTURE.read_text(encoding="utf-8"))
    assert cands and all(c.datasheet_url is None for c in cands)


def test_resolve_returns_the_datasheet_anchor_from_the_product_page(monkeypatch):
    adapter = MiniCircuitsAdapter()
    monkeypatch.setattr(adapter, "_get", lambda url: _PRODUCT_PAGE_HTML)
    cand = Candidate(model="ZHL-2-S+", manufacturer="Mini-Circuits",
                     url="https://www.minicircuits.com/WebStore/dashboard.html?model=ZHL-2-S%2B",
                     raw_params={}, source="table")
    assert adapter.resolve_datasheet_url(cand) == (
        "https://www.minicircuits.com/pdfs/ZHL-2-S+.pdf"
    )


def test_resolve_returns_none_on_fetch_failure(monkeypatch):
    from rf_finder.adapters.base import AdapterError
    adapter = MiniCircuitsAdapter()
    def _fail(url):
        raise AdapterError(manufacturer="Mini-Circuits", context="boom")
    monkeypatch.setattr(adapter, "_get", _fail)
    cand = Candidate(model="ZHL-2-S+", manufacturer="Mini-Circuits", url="x",
                     raw_params={}, source="table")
    assert adapter.resolve_datasheet_url(cand) is None


def test_resolve_returns_none_when_page_has_no_datasheet_link(monkeypatch):
    adapter = MiniCircuitsAdapter()
    monkeypatch.setattr(adapter, "_get", lambda url: "<html><body>no link</body></html>")
    cand = Candidate(model="ZHL-2-S+", manufacturer="Mini-Circuits", url="x",
                     raw_params={}, source="table")
    assert adapter.resolve_datasheet_url(cand) is None


def test_product_url_percent_encodes_the_plus(monkeypatch):
    """7.9 regression: an un-encoded '+' yields a 200 page with no datasheet link.

    The product page URL must carry '%2B', so resolve() fetches the encoded URL.
    """
    seen = {}
    def _capture(url):
        seen["url"] = url
        return _PRODUCT_PAGE_HTML
    adapter = MiniCircuitsAdapter()
    # url unset -> resolve builds it from the model, which is where encoding happens
    monkeypatch.setattr(adapter, "_get", _capture)
    cand = Candidate(model="ZHL-2-S+", manufacturer="Mini-Circuits", url="",
                     raw_params={}, source="table")
    adapter.resolve_datasheet_url(cand)
    assert "%2B" in seen["url"] and "S+" not in seen["url"]
