"""Offline unit tests for the Marki Microwave adapter (T9).

All tests use local HTML fixtures captured from the live site — no network
access required.  The ``test_search_live`` test is marked ``@pytest.mark.network``
and is skipped in the default ``-m "not network"`` run.

Live-structure facts exercised here (see the adapter docstring):
  * the part number is a row ``<th>`` carrying the product href; the data ``<td>``
    cells align to ``headers[1:]`` (off-by-one), and
  * Size / VDD / Temperature come from a second per-product page fetch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.marki import MarkiMicrowaveAdapter
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent.parent / "fixtures"
SEARCH_FIXTURE = FIXTURES / "marki_amplifiers.html"
PRODUCT_FIXTURE = FIXTURES / "marki_product_adm11425psm.html"


def _load_candidates() -> list[Candidate]:
    adapter = MarkiMicrowaveAdapter()
    return adapter._parse_search_html(SEARCH_FIXTURE.read_text(encoding="utf-8"))


def _by_model(model: str) -> Candidate:
    return next(c for c in _load_candidates() if c.model == model)


# ---------------------------------------------------------------------------
# Pass 1 — search table
# ---------------------------------------------------------------------------

def test_parse_fixture_returns_candidates():
    assert len(_load_candidates()) == 3


def test_candidate_model_manufacturer_source():
    c = _load_candidates()[0]
    assert c.model == "ADM-11425PSM"
    assert c.manufacturer == "Marki Microwave"
    assert c.source == "table"


def test_part_number_th_offset_mapping():
    """The leading <th> part number must not shift the <td>->header alignment.

    ADM-11425PSM: Gain 23.0 dB, NF 3.3 dB, OIP3 (->IP3) 19.5 dBm, P1dB 10.5 dBm.
    A naive header[i]->cell[i] mapping would mis-assign every column.
    """
    c = _by_model("ADM-11425PSM")
    assert c.raw_params["Gain"] == RawValue(value=23.0, unit="dB")
    assert c.raw_params["NF"] == RawValue(value=3.3, unit="dB")
    assert c.raw_params["IP3"] == RawValue(value=19.5, unit="dBm")
    assert c.raw_params["P1dB"] == RawValue(value=10.5, unit="dBm")


def test_freq_range_is_rawvalue_tuple_in_ghz():
    c = _by_model("ADM-11425PSM")
    rv = c.raw_params["freq_range"]
    assert isinstance(rv, RawValue)
    assert isinstance(rv.value, tuple)
    assert rv.unit == "GHz"
    assert rv.value == (4.0, 40.0)


def test_missing_cell_is_absent_not_none():
    """ADM-11425PSM lists Psat '-'; the key must be absent, not stored as None."""
    c = _by_model("ADM-11425PSM")
    assert "Psat" not in c.raw_params


def test_dc_coupled_low_edge_is_zero():
    """AMM-11059CH is DC-coupled (F Low '0' -> 0.0 GHz), kept not dropped."""
    rv = _by_model("AMM-11059CH").raw_params["freq_range"]
    assert rv.value == (0.0, 50.0)
    assert rv.unit == "GHz"


def test_product_url_from_href():
    """The URL is read from the row <th> <a href>, absolutised against the host."""
    c = _by_model("AMM-11561CH")
    assert c.url == (
        "https://markimicrowave.com/products/bare-die/amplifiers/amm-11561ch/"
    )


def test_parse_total_from_count_string():
    adapter = MarkiMicrowaveAdapter()
    assert adapter._parse_total(SEARCH_FIXTURE.read_text(encoding="utf-8")) == 123


def test_no_table_returns_empty_list():
    """A challenge / non-table page yields no candidates (not an error)."""
    adapter = MarkiMicrowaveAdapter()
    assert adapter._parse_search_html("<html><body>Just a moment…</body></html>") == []


# ---------------------------------------------------------------------------
# Pass 2 — per-product page (Size / VDD / Temperature)
# ---------------------------------------------------------------------------

def _product_details(model: str) -> dict[str, RawValue]:
    adapter = MarkiMicrowaveAdapter()
    return adapter._extract_product_details(
        PRODUCT_FIXTURE.read_text(encoding="utf-8"), model
    )


def test_size_from_matching_variant_row():
    """Size is taken from the row whose part number matches the model ("4 x 4 mm"),
    not the EVB variant row whose Size is '-'."""
    extra = _product_details("ADM-11425PSM")
    assert extra["Size"] == RawValue(value=4.0, unit="mm")


def test_size_absent_for_evb_variant():
    """The EVB variant row lists Size '-', so Size must be absent for it."""
    assert "Size" not in _product_details("EVB-ADM-11425P")


def test_vdd_from_js_payload():
    """VDD comes from power_supply_voltage:[{value:"5"}] -> (5.0, 5.0) V."""
    assert _product_details("ADM-11425PSM")["VDD"] == RawValue(value=(5.0, 5.0), unit="V")


def test_temperature_is_degenerate_range_in_degc():
    """temperature:"25" -> a single characterisation point stored as (25, 25) °C."""
    rv = _product_details("ADM-11425PSM")["Temperature"]
    assert rv.unit == "degC"
    assert rv.value == (25.0, 25.0)


def test_enrichment_gated_off_without_relevant_constraint():
    """A freq-only query must NOT trigger product-page params on the candidate."""
    spec = QuerySpec(
        component_type="amplifier",
        constraints=[
            ParamConstraint(
                canonical_name="Gain",
                comparison="min",
                value=10.0,
                range=None,
                unit="dB",
            )
        ],
    )
    assert MarkiMicrowaveAdapter()._needs_product_pages(spec) is False


def test_enrichment_gated_on_for_size_constraint():
    spec = QuerySpec(
        component_type="amplifier",
        constraints=[
            ParamConstraint(
                canonical_name="Size",
                comparison="max",
                value=5.0,
                range=None,
                unit="mm",
            )
        ],
    )
    assert MarkiMicrowaveAdapter()._needs_product_pages(spec) is True


# ---------------------------------------------------------------------------
# Integration test (network, skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_search_live():
    """Live search against the Marki Microwave site (requires network)."""
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
    results = MarkiMicrowaveAdapter().search(spec)
    assert len(results) > 100  # catalogue is ~123 amplifiers
    assert all(c.manufacturer == "Marki Microwave" for c in results)
    assert all("markimicrowave.com" in c.url for c in results)
