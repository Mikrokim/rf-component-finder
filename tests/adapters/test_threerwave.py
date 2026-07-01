"""Offline unit tests for the 3rWave adapter.

All tests use the local HTML fixture — no network access required.  The
``test_search_live`` test is marked ``@pytest.mark.network`` and is skipped in
the default ``-m "not network"`` run (and would in any case be blocked by the
Etrog/safepage content filter on the dev machine — see threerwave-plan.md
OQ-3W-10).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.base import AdapterError
from rf_finder.adapters.threerwave import ThreeRWaveAdapter
from rf_finder.models import Candidate, RawValue

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent.parent / "fixtures" / "threerwave_amplifier.html"


def _load_candidates() -> list[Candidate]:
    adapter = ThreeRWaveAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    return adapter._parse_html(html)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_parses_both_pa_and_lna_tables():
    """All rows from both the PA (3) and LNA (2) tables are returned."""
    candidates = _load_candidates()
    assert len(candidates) == 5
    models = {c.model for c in candidates}
    assert "MP020M060GS30B" in models   # PA
    assert "ML00100400S24A" in models   # LNA


def test_candidate_model_and_manufacturer():
    """First candidate has correct manufacturer, source, and non-empty model."""
    c = _load_candidates()[0]
    assert c.manufacturer == "3rWave"
    assert c.source == "table"
    assert c.model


def test_freq_range_is_rawvalue_tuple_in_ghz():
    """freq_range is combined from Start+Stop, already in GHz (no conversion)."""
    c = next(x for x in _load_candidates() if x.model == "MP020M060GS30B")
    rv = c.raw_params["freq_range"]
    assert isinstance(rv, RawValue)
    assert isinstance(rv.value, tuple)
    assert rv.unit == "GHz"
    assert rv.value == (0.02, 6.0)


def test_present_scalar_params():
    """A fully-specified PA row carries Gain, Psat, NF, VDD."""
    c = next(x for x in _load_candidates() if x.model == "MP020M060GS30B")
    assert c.raw_params["Gain"] == RawValue(value=30.0, unit="dB")
    assert c.raw_params["Psat"] == RawValue(value=30.0, unit="dBm")
    assert c.raw_params["NF"] == RawValue(value=12.0, unit="dB")
    assert c.raw_params["VDD"] == RawValue(value=0.4, unit="V")


def test_missing_cell_is_absent_not_none():
    """'-' cells must be absent from raw_params (not stored as None)."""
    # MP000003N1500A has NF, Drain Voltage = '-'.
    c = next(x for x in _load_candidates() if x.model == "MP000003N1500A")
    assert "NF" not in c.raw_params
    assert "VDD" not in c.raw_params
    # But Gain/Psat that are present remain.
    assert c.raw_params["Gain"] == RawValue(value=62.0, unit="dB")


def test_blank_psat_row_is_partial_not_fail():
    """An LNA row with a blank Psat cell simply omits Psat (Verifier → UNKNOWN)."""
    c = next(x for x in _load_candidates() if x.model == "ML37504250W09A")
    assert "Psat" not in c.raw_params
    assert c.raw_params["NF"] == RawValue(value=0.9, unit="dB")


def test_deferred_params_never_emitted():
    """P1dB, IP3, MSL, Temperature, Size have no columns / are deferred."""
    for c in _load_candidates():
        for absent in ("P1dB", "IP3", "MSL", "Temperature", "Size"):
            assert absent not in c.raw_params


def test_url_from_anchor_when_present():
    """A per-part <a href> is used (host-prefixed) for the Candidate URL."""
    c = next(x for x in _load_candidates() if x.model == "MP020M060GS30B")
    assert c.url == "https://3rwave.com/product/mp020m060gs30b/"


def test_url_falls_back_to_highlight_link_when_no_anchor():
    """Rows without a per-part link get a text-fragment deep link that
    highlights the exact Part Number on the shared /amplifier/ page."""
    c = next(x for x in _load_candidates() if x.model == "MP37504250CW40B")
    assert c.url == "https://3rwave.com/amplifier/#:~:text=MP37504250CW40B"


def test_raises_adaptererror_when_no_tablepress():
    """_parse_html must raise AdapterError when no table.tablepress is present."""
    adapter = ThreeRWaveAdapter()
    with pytest.raises(AdapterError):
        adapter._parse_html("<html><body>no table here</body></html>")


def test_content_filter_block_stub_is_legible_error():
    """A content-filter (Etrog/safepage) block stub raises a clear AdapterError."""
    block = (
        '<html><head></head><body><script>window.location='
        '"https://safepage.etrog.net.il/?a=block/block1&cause=url_level_uu";'
        "</script></body></html>"
    )
    adapter = ThreeRWaveAdapter()
    with pytest.raises(AdapterError, match="content filter"):
        adapter._parse_html(block)


# ---------------------------------------------------------------------------
# Integration test (network, skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_search_live():
    """Live search against 3rwave.com (requires network; may be filter-blocked)."""
    from rf_finder.models import ParamConstraint, QuerySpec

    spec = QuerySpec(
        component_type="amplifier",
        constraints=[
            ParamConstraint(
                canonical_name="freq_range",
                comparison="contains",
                value=None,
                range=(3.75, 4.25),
                unit="GHz",
            ),
        ],
    )
    adapter = ThreeRWaveAdapter()
    results = adapter.search(spec)
    assert len(results) > 0
    assert all(c.manufacturer == "3rWave" for c in results)
