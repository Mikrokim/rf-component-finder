"""Offline unit tests for the MACOM adapter (macom-plan.md §7).

All tests use the local HTML fixture (a trimmed slice of the live "All
Amplifiers" page, each row carrying its real ``data-part`` JSON) — no network.
``test_search_live`` is marked ``@pytest.mark.network`` and skipped by default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.macom import MacomAdapter
from rf_finder.models import Candidate, RawValue

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

FIXTURE = Path(__file__).parent.parent / "fixtures" / "macom_all_amplifiers.html"


def _load_candidates() -> list[Candidate]:
    adapter = MacomAdapter()
    html = FIXTURE.read_text(encoding="utf-8")
    return adapter._parse_html(html)


def _by_model(model: str) -> Candidate:
    return next(c for c in _load_candidates() if c.model == model)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_parse_fixture_returns_all_rows():
    """Every data-part row in the fixture becomes a Candidate."""
    candidates = _load_candidates()
    assert len(candidates) == 6


def test_candidate_model_manufacturer_source():
    c = _load_candidates()[0]
    assert c.manufacturer == "MACOM"
    assert c.source == "table"
    assert c.model  # non-empty


def test_freq_range_combined_in_mhz():
    """Min + Max Frequency combine into one RawValue((low, high), 'MHz')."""
    c = _by_model("MAAL-011182")
    rv = c.raw_params["freq_range"]
    assert isinstance(rv, RawValue)
    assert isinstance(rv.value, tuple)
    assert rv.unit == "MHz"
    assert rv.value == (2000.0, 20000.0)


def test_rich_part_all_mapped_params():
    """MAAL-011182 exposes freq + Gain/OIP3/P1dB/NF (no PSAT for this part)."""
    c = _by_model("MAAL-011182")
    assert c.raw_params["Gain"] == RawValue(15.0, "dB")
    assert c.raw_params["OIP3"] == RawValue(24.0, "dBm")
    assert c.raw_params["P1dB"] == RawValue(14.0, "dBm")
    assert c.raw_params["NF"] == RawValue(1.5, "dB")
    assert "Pout" not in c.raw_params


def test_missing_params_absent_not_none():
    """CGH40006S has only freq + Gain; absent specs must not appear as keys."""
    c = _by_model("CGH40006S")
    assert c.raw_params["freq_range"].value == (0.0, 6000.0)
    assert c.raw_params["Gain"] == RawValue(11.0, "dB")
    for absent in ("P1dB", "OIP3", "NF", "Pout"):
        assert absent not in c.raw_params


def test_noise_figure_synonym_maps_to_nf():
    """A 'Noise Figure' spec (not 'NF') still maps to canonical NF."""
    c = _by_model("MAAM-011275")
    assert c.raw_params["NF"] == RawValue(5.0, "dB")


def test_psat_maps_to_pout_in_dbm():
    """'PSAT' (dBm) maps to canonical Pout; discontinued part still returned."""
    c = _by_model("MAPC-A1524")
    assert c.raw_params["Pout"] == RawValue(55.0, "dBm")
    assert c.raw_params["Gain"] == RawValue(16.0, "dB")


def test_discontinued_part_is_returned():
    """Discontinued parts are not filtered out by the adapter."""
    models = {c.model for c in _load_candidates()}
    assert "MAPC-A1524" in models


def test_units_normalized_to_ontology_not_source():
    """Power params are stored in canonical units regardless of source 'uom'."""
    c = _by_model("MAAL-011182")
    assert c.raw_params["P1dB"].unit == "dBm"
    assert c.raw_params["OIP3"].unit == "dBm"


def test_high_frequency_part():
    """MAAL-011111 is a 22000–38000 MHz part (stored in MHz)."""
    c = _by_model("MAAL-011111")
    assert c.raw_params["freq_range"].value == (22000.0, 38000.0)


def test_control_char_blob_parses():
    """A blob containing literal control chars parses (strict=False)."""
    # CGH40006S's data-part JSON contains literal newlines/tabs.
    assert _by_model("CGH40006S") is not None


def test_url_built_from_part_url():
    c = _by_model("MAAL-011182")
    assert c.url == "https://www.macom.com/products/product-detail/MAAL-011182"
    assert c.model in c.url


def test_raises_adaptererror_when_no_data_part():
    from rf_finder.adapters.base import AdapterError

    adapter = MacomAdapter()
    with pytest.raises(AdapterError):
        adapter._parse_html("<html><body>no data-part here</body></html>")


# ---------------------------------------------------------------------------
# Integration test (network, skipped by default)
# ---------------------------------------------------------------------------

@pytest.mark.network
def test_search_live():
    """Live search against macom.com (requires network)."""
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
    results = MacomAdapter().search(spec)
    assert len(results) > 500
    assert all(c.manufacturer == "MACOM" for c in results)
