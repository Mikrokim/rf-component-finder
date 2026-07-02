"""Offline unit tests for the Qorvo adapter (scrapes /products/product-list/)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.base import AdapterError
from rf_finder.adapters.qorvo import (
    QorvoAdapter,
    _norm,
    _num,
    _vdd,
)
from rf_finder.models import Candidate, RawValue

FIXTURE = Path(__file__).parent.parent / "fixtures" / "qorvo_product_list.html"


def _load_candidates() -> list[Candidate]:
    return QorvoAdapter()._parse_html(FIXTURE.read_text(encoding="utf-8"))


def _by(model: str) -> Candidate:
    return next(c for c in _load_candidates() if c.model == model)


# ---------------------------------------------------------------------------
# Category filtering (Layer 1)
# ---------------------------------------------------------------------------

def test_only_amplifier_categories_kept() -> None:
    models = {c.model for c in _load_candidates()}
    # amplifier rows kept
    assert {"CMD263", "CMD192", "QPA2311", "QPB0206N", "QPL1827"} <= models
    # the Discrete Switches block is filtered out
    assert "SW9999" not in models


def test_model_url_manufacturer_source() -> None:
    c = _by("CMD263")
    assert c.manufacturer == "Qorvo"
    assert c.source == "table"
    assert c.url == "https://www.qorvo.com/products/p/CMD263"


# ---------------------------------------------------------------------------
# Frequency
# ---------------------------------------------------------------------------

def test_freq_range_ghz() -> None:
    assert _by("CMD263").raw_params["freq_range"] == RawValue((5.0, 11.0), "GHz")


def test_freq_min_dc_zero_low_edge() -> None:
    """CMD192 is DC-coupled: 'Frequency Min' = 'DC' -> 0.0 low edge."""
    assert _by("CMD192").raw_params["freq_range"] == RawValue((0.0, 20.0), "GHz")


def test_freq_unit_read_from_subtitle() -> None:
    """CATV frequency columns are MHz (per-column subtitle), not the GHz default."""
    assert _by("QPL1827").raw_params["freq_range"] == RawValue((50.0, 1800.0), "MHz")


# ---------------------------------------------------------------------------
# VDD (Voltage / Vd, ranges and multi-value)
# ---------------------------------------------------------------------------

def test_vdd_range_to_separator() -> None:
    """Vd '5 to 8' -> (5.0, 8.0); Vg is ignored."""
    assert _by("CMD192").raw_params["VDD"] == RawValue((5.0, 8.0), "V")


def test_vdd_single_value() -> None:
    assert _by("QPA2311").raw_params["VDD"] == RawValue((30.0, 30.0), "V")


def test_vdd_multi_value_is_discrete_list() -> None:
    """A multi-option supply '3, 5, 8' is kept as a discrete list, not a range.

    (A (3, 8) band would wrongly accept 4 V; the part supports 3/5/8 V only.)
    """
    assert _by("CMDDIE").raw_params["VDD"] == RawValue([3.0, 5.0, 8.0], "V")


# ---------------------------------------------------------------------------
# Messy scalar values (>, <, qualifiers) and per-category schema
# ---------------------------------------------------------------------------

def test_greater_than_prefix_stripped() -> None:
    """QPAGT: Psat '> 41' -> 41.0 and Gain '> 24' -> 24.0."""
    c = _by("QPAGT")
    assert c.raw_params["Psat"] == RawValue(41.0, "dBm")
    assert c.raw_params["Gain"] == RawValue(24.0, "dB")


def test_spatium_uses_small_signal_gain() -> None:
    """Spatium maps 'Small Signal Gain' (30-33 -> 30), not 'Power Gain' (18-19)."""
    c = _by("QPB0206N")
    assert c.raw_params["Gain"] == RawValue(30.0, "dB")
    assert c.raw_params["Psat"] == RawValue(250.0, "W")   # Psat unit is W for Spatium


def test_pa_row_has_psat_but_no_nf_or_ip3() -> None:
    """Power Amplifiers have no NF/OIP3 columns -> those params absent; Psat present."""
    c = _by("QPA2311")
    assert c.raw_params["Psat"] == RawValue(47.0, "dBm")
    assert "NF" not in c.raw_params
    assert "IP3" not in c.raw_params


def test_lna_scalars_mapped() -> None:
    c = _by("CMD263")
    assert c.raw_params["Gain"] == RawValue(23.0, "dB")
    assert c.raw_params["NF"] == RawValue(1.4, "dB")
    assert c.raw_params["P1dB"] == RawValue(11.0, "dBm")
    assert c.raw_params["IP3"] == RawValue(23.0, "dBm")


def test_empty_scalar_is_absent() -> None:
    """CMDDIE has an empty NF cell -> NF absent (part still kept)."""
    c = _by("CMDDIE")
    assert "NF" not in c.raw_params
    assert c.raw_params["P1dB"] == RawValue(10.0, "dBm")


def test_size_msl_temperature_never_emitted() -> None:
    """v1 leaves Size/MSL/Temperature UNKNOWN (Option A)."""
    for c in _load_candidates():
        assert not ({"Size", "MSL", "Temperature"} & set(c.raw_params))


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_missing_container_raises_adaptererror() -> None:
    with pytest.raises(AdapterError):
        QorvoAdapter()._parse_html("<html><body>no product list</body></html>")


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_norm_collapses_punctuation_and_at() -> None:
    assert _norm("Gain @ 0 dB Atten") == "gain 0 db atten"
    assert _norm("OP1dB") == "op1db"
    assert _norm("Frequency Min") == "frequency min"


@pytest.mark.parametrize("sentinel", ["", "   ", "-", "--", "N/A", "NA", "n/a"])
def test_num_sentinels_return_none(sentinel) -> None:
    assert _num(sentinel) is None


def test_num_parses_plain_and_zero() -> None:
    assert _num("10.2") == 10.2
    assert _num("0") == 0.0
    assert _num("-1") == -1.0


def test_num_dc_is_zero() -> None:
    assert _num("DC") == 0.0
    assert _num("dc") == 0.0


def test_num_strips_comparators() -> None:
    assert _num("> 40") == 40.0
    assert _num("< 3.5") == 3.5
    assert _num(">= 26") == 26.0


def test_num_ignores_trailing_qualifiers_and_units() -> None:
    assert _num("35 (S21)") == 35.0
    assert _num("13.4 @ 1950 MHz") == 13.4
    assert _num("18 Vdc") == 18.0


def test_num_thousands_vs_list() -> None:
    assert _num("1,000") == 1000.0     # thousands separator
    assert _num("9, 11") == 9.0        # value list -> first value


def test_vdd_range_and_single() -> None:
    """A 'to' range and a single value are both continuous (low, high) tuples."""
    assert _vdd("2 to 4.5") == (2.0, 4.5)
    assert _vdd("30") == (30.0, 30.0)
    assert _vdd("18 Vdc") == (18.0, 18.0)


def test_vdd_multi_value_and_slash_are_discrete_lists() -> None:
    """Comma/slash supplies are discrete options → a list (sorted, de-duped)."""
    assert _vdd("3, 5, 8") == [3.0, 5.0, 8.0]
    assert _vdd("5/8") == [5.0, 8.0]
    assert _vdd("6, 28") == [6.0, 28.0]


def test_vdd_sentinels_return_none() -> None:
    assert _vdd("") is None
    assert _vdd("N/A") is None
