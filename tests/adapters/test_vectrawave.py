"""Offline unit tests for the VectraWave adapter (transposed Divi tables)."""

from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.adapters.base import AdapterError
from rf_finder.adapters.vectrawave import VectraWaveAdapter, _normalize, _num
from rf_finder.models import Candidate, RawValue

FIXTURE = Path(__file__).parent.parent / "fixtures" / "vectrawave_mmic.html"


def _load() -> list[Candidate]:
    return VectraWaveAdapter()._parse_html(FIXTURE.read_text(encoding="utf-8"))


def _by(model: str) -> Candidate:
    return next(c for c in _load() if c.model == model)


# ---------------------------------------------------------------------------
# Section filter + transposed parsing
# ---------------------------------------------------------------------------

def test_only_amplifier_sections_returned() -> None:
    models = {c.model for c in _load()}
    assert {"VM042D", "VM088D", "VM017D"} <= models   # High Power + Low Noise
    assert "VM700D" not in models                      # ATTENUATOR filtered out


def test_transposed_products_parsed() -> None:
    c = _by("VM042D")
    assert c.manufacturer == "VectraWave"
    assert c.source == "table"


def test_freq_range_from_min_max_ghz() -> None:
    assert _by("VM042D").raw_params["freq_range"] == RawValue((8.0, 12.0), "GHz")
    assert _by("VM088D").raw_params["freq_range"] == RawValue((8.0, 10.5), "GHz")


def test_pout_maps_to_psat_not_p1db() -> None:
    """High Power: 'Pout' is the saturated output power -> Psat, and no P1dB."""
    c = _by("VM042D")
    assert c.raw_params["Psat"] == RawValue(40.0, "dBm")
    assert "P1dB" not in c.raw_params


def test_op1db_maps_to_p1db_in_lna() -> None:
    assert _by("VM017D").raw_params["P1dB"] == RawValue(18.0, "dBm")


def test_psat_and_nf_in_lna_section() -> None:
    c = _by("VM017D")
    assert c.raw_params["Psat"] == RawValue(21.0, "dBm")
    assert c.raw_params["NF"] == RawValue(1.6, "dB")


def test_power_amp_has_no_nf() -> None:
    assert "NF" not in _by("VM042D").raw_params


def test_vdd_from_both_voltage_labels() -> None:
    # High Power uses "Voltage V" (+8); Low Noise uses "DrainVoltage V" (5.0)
    assert _by("VM042D").raw_params["VDD"] == RawValue((8.0, 8.0), "V")
    assert _by("VM017D").raw_params["VDD"] == RawValue((5.0, 5.0), "V")


def test_control_voltage_not_mapped_to_vdd() -> None:
    """VM017D has a ControlVoltage row (3.0) — VDD must stay the DrainVoltage (5.0)."""
    assert _by("VM017D").raw_params["VDD"] == RawValue((5.0, 5.0), "V")


def test_no_ip3_msl_size_temp_from_table() -> None:
    for c in _load():
        for absent in ("IP3", "MSL", "Size", "Temperature"):
            assert absent not in c.raw_params


def test_url_is_datasheet_pdf() -> None:
    assert _by("VM042D").url == (
        "https://vectrawave.com/wp-content/uploads/2025/02/VM042D-DS-Rev3.0-Ed1.1.pdf"
    )


def test_missing_modules_raises_adaptererror() -> None:
    with pytest.raises(AdapterError):
        VectraWaveAdapter()._parse_html("<html><body>no tables</body></html>")


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

def test_normalize() -> None:
    assert _normalize("FrequencyMin GHZ") == "frequencymin ghz"
    assert _normalize("OP1dB dBm") == "op1db dbm"
    assert _normalize("DrainVoltage V") == "drainvoltage v"


@pytest.mark.parametrize("sentinel", ["", "  ", "-", "NA", "TBD"])
def test_num_sentinels(sentinel) -> None:
    assert _num(sentinel) is None


def test_num_values() -> None:
    assert _num("+8") == 8.0      # leading-sign supply value
    assert _num("40.0") == 40.0
    assert _num("abc") is None
