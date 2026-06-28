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
    """ZX60-P103LN+ has all 6 RF params present in raw_params."""
    candidates = _load_candidates()
    c = next(x for x in candidates if x.model == "ZX60-P103LN+")
    expected_keys = {"freq_range", "Gain", "NF", "P1dB", "Psat", "IP3"}
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
