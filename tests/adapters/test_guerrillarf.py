"""Offline unit tests for the Guerrilla RF adapter (scrapes amplifiers.html)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.base import AdapterError
from rf_finder.adapters.guerrillarf import (
    GuerrillaRFAdapter,
    _normalize_header,
    _num,
)
from rf_finder.models import Candidate, RawValue

FIXTURE = Path(__file__).parent.parent / "fixtures" / "guerrillarf_amplifiers.html"


def _load_candidates() -> list[Candidate]:
    return GuerrillaRFAdapter()._parse_html(FIXTURE.read_text(encoding="utf-8"))


def _by(model: str) -> Candidate:
    return next(c for c in _load_candidates() if c.model == model)


# ---------------------------------------------------------------------------
# Parsing both tables
# ---------------------------------------------------------------------------

def test_parses_both_tables() -> None:
    models = {c.model for c in _load_candidates()}
    assert {"GRF2003", "GRF2004", "GRF2010"} <= models  # LNA table
    assert "GRF0005" in models                           # PA table


def test_model_url_manufacturer_source() -> None:
    c = _by("GRF2003")
    assert c.manufacturer == "Guerrilla RF"
    assert c.source == "table"
    assert c.url == "https://www.guerrilla-rf.com/products/detail/sku/GRF2003"


def test_freq_range_from_min_max_ghz() -> None:
    c = _by("GRF2003")
    assert c.raw_params["freq_range"] == RawValue((0.1, 10.0), "GHz")


def test_dc_coupled_zero_low_edge() -> None:
    """GRF0005 (PA table) is DC-coupled: Min Freq '0' keeps the 0 low edge."""
    c = _by("GRF0005")
    assert c.raw_params["freq_range"] == RawValue((0.0, 12.0), "GHz")


def test_vdd_range_parsed() -> None:
    assert _by("GRF2003").raw_params["VDD"] == RawValue((2.7, 5.0), "V")
    assert _by("GRF0005").raw_params["VDD"] == RawValue((28.0, 40.0), "V")


def test_lna_scalars_mapped() -> None:
    c = _by("GRF2003")
    assert c.raw_params["Gain"] == RawValue(12.0, "dB")
    assert c.raw_params["NF"] == RawValue(3.5, "dB")
    assert c.raw_params["P1dB"] == RawValue(15.0, "dBm")
    assert c.raw_params["IP3"] == RawValue(29.0, "dBm")


def test_pa_row_has_psat_but_no_nf_column() -> None:
    """The PA table has no NF/OIP3 columns, so those params are absent; Psat present."""
    c = _by("GRF0005")
    assert c.raw_params["Psat"] == RawValue(38.7, "dBm")
    assert "NF" not in c.raw_params
    assert "IP3" not in c.raw_params


def test_empty_scalar_is_absent() -> None:
    """GRF2004 has an empty OIP3 cell -> IP3 absent."""
    c = _by("GRF2004")
    assert "IP3" not in c.raw_params
    assert c.raw_params["NF"] == RawValue(1.9, "dB")


def test_empty_vdd_is_omitted() -> None:
    """GRF2010 has an empty Vdd Range cell -> no VDD."""
    c = _by("GRF2010")
    assert "VDD" not in c.raw_params
    assert c.raw_params["freq_range"] == RawValue((0.05, 5.0), "GHz")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_missing_tables_raises_adaptererror() -> None:
    with pytest.raises(AdapterError):
        GuerrillaRFAdapter()._parse_html("<html><body>no tables</body></html>")


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_normalize_header_collapses_punctuation() -> None:
    assert _normalize_header("Gain(dB)") == "gain db"
    assert _normalize_header("Gain (dB)") == "gain db"
    assert _normalize_header("Vdd Range (V)") == "vdd range v"
    assert _normalize_header("Min Freq (GHz)") == "min freq ghz"


@pytest.mark.parametrize("sentinel", ["", "  ", "-", "NA", "N/A"])
def test_num_sentinels_return_none(sentinel) -> None:
    assert _num(sentinel) is None


def test_num_parses_values() -> None:
    assert _num("10.2") == 10.2
    assert _num("0") == 0.0
    assert _num("abc") is None
