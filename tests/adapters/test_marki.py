"""Offline unit tests for the Marki Microwave adapter (T9).

All tests use local HTML fixtures captured from the live site — no network
access required.  The ``test_search_live`` test is marked ``@pytest.mark.network``
and is skipped in the default ``-m "not network"`` run.

Live-structure facts exercised here (see the adapter docstring):
  * the part number is a row ``<th>`` carrying the product href; the data ``<td>``
    cells align to ``headers[1:]`` (off-by-one), and
  * only the all-products search table is scraped — Size / VDD / Temperature are
    NOT extracted (they verify as UNKNOWN).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.base import AdapterError
from rf_finder.adapters.marki import MarkiMicrowaveAdapter
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent.parent / "fixtures"
SEARCH_FIXTURE = FIXTURES / "marki_amplifiers.html"


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
# Table-only guarantee — off-table params are never emitted
# ---------------------------------------------------------------------------

def test_off_table_params_are_not_emitted():
    """Size / VDD / Temperature / MSL live only off the search table; this
    table-only adapter must never populate them (they verify as UNKNOWN)."""
    off_table = {"Size", "VDD", "Temperature", "MSL"}
    for c in _load_candidates():
        assert off_table.isdisjoint(c.raw_params), (
            f"{c.model} unexpectedly carries off-table params: "
            f"{off_table & set(c.raw_params)}"
        )


def test_search_returns_table_candidates_unchanged(monkeypatch):
    """search() returns the parsed table rows without any per-product enrichment
    fetch — a Size constraint no longer triggers extra requests."""
    adapter = MarkiMicrowaveAdapter()
    monkeypatch.setattr(adapter, "_fetch_search_candidates", _load_candidates)

    def _fail_fetch(*_a, **_k):  # any product-page fetch would be a regression
        raise AssertionError("search() must not fetch product pages")

    monkeypatch.setattr(adapter, "_fetch", _fail_fetch)

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
    results = adapter.search(spec)
    assert [c.model for c in results] == [c.model for c in _load_candidates()]


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


# ---------------------------------------------------------------------------
# Datasheet link (case 2, with a twist: search() reads the landing PAGE from
# the Datasheet column; resolve_datasheet_url upgrades it to the real PDF)
# ---------------------------------------------------------------------------

_LANDING_HTML = """
<html><body>
  <a href="https://markimicrowave.com/assets/9af9-uuid/MM_Catalog_SMT_Die.pdf">Online Catalog</a>
  <a href="https://markimicrowave.com/assets/abc123/ADM-11425PSM Amplifier.pdf">Download PDF</a>
</body></html>
"""


def test_search_reads_the_landing_page_and_makes_no_per_part_request() -> None:
    """search() carries the Datasheet-column landing PAGE, not the PDF, no fetch."""
    cands = _load_candidates()
    cand = next(c for c in cands if c.model == "ADM-11425PSM")
    assert cand.datasheet_url == (
        "https://markimicrowave.com/products/surface-mount/amplifiers/adm-11425psm/datasheet/"
    )
    assert cand.datasheet_url.endswith("/datasheet/")  # a page, not a .pdf


def test_resolve_returns_the_download_pdf_not_the_catalogue(monkeypatch) -> None:
    """The page also links an 'Online Catalog' PDF — a valid PDF that is a trap."""
    adapter = MarkiMicrowaveAdapter()

    class _Resp:
        text = _LANDING_HTML

    monkeypatch.setattr(adapter, "_request", lambda url: _Resp())
    cand = Candidate(model="ADM-11425PSM", manufacturer="Marki Microwave", url="x",
                     raw_params={}, source="table",
                     datasheet_url="https://markimicrowave.com/…/adm-11425psm/datasheet/")
    got = adapter.resolve_datasheet_url(cand)
    assert got == "https://markimicrowave.com/assets/abc123/ADM-11425PSM Amplifier.pdf"
    assert "Catalog" not in got


def test_resolve_returns_none_on_fetch_failure(monkeypatch) -> None:
    adapter = MarkiMicrowaveAdapter()

    def _fail(url):
        raise AdapterError(manufacturer="Marki Microwave", context="boom")

    monkeypatch.setattr(adapter, "_request", _fail)
    cand = Candidate(model="X", manufacturer="Marki Microwave", url="x",
                     raw_params={}, source="table",
                     datasheet_url="https://markimicrowave.com/x/datasheet/")
    assert adapter.resolve_datasheet_url(cand) is None


def test_resolve_never_falls_back_to_the_html_landing_page(monkeypatch) -> None:
    """A page with no 'Download PDF' link must yield None, NOT the HTML page URL."""
    adapter = MarkiMicrowaveAdapter()

    class _Resp:
        text = "<html><body>no download link</body></html>"

    landing = "https://markimicrowave.com/x/datasheet/"
    monkeypatch.setattr(adapter, "_request", lambda url: _Resp())
    cand = Candidate(model="X", manufacturer="Marki Microwave", url="x",
                     raw_params={}, source="table", datasheet_url=landing)
    got = adapter.resolve_datasheet_url(cand)
    assert got is None and got != landing


def test_resolve_returns_none_when_candidate_has_no_landing_page() -> None:
    adapter = MarkiMicrowaveAdapter()
    cand = Candidate(model="X", manufacturer="Marki Microwave", url="x",
                     raw_params={}, source="table", datasheet_url=None)
    assert adapter.resolve_datasheet_url(cand) is None
