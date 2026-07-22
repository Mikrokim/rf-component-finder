"""Offline unit tests for the Analog Devices RF amplifier adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rf_finder.adapters.analogdevices import (
    AnalogDevicesAdapter,
    _cell_value,
    _parse_float,
)
from rf_finder.adapters.base import AdapterError
from rf_finder.models import Candidate, RawValue

FIXTURE = Path(__file__).parent.parent / "fixtures" / "analogdevices_rfamps.json"


def _load_candidates() -> list[Candidate]:
    adapter = AnalogDevicesAdapter()
    json_text = FIXTURE.read_text(encoding="utf-8")
    return adapter._parse_json(json_text)


def test_parse_fixture_returns_candidates() -> None:
    candidates = _load_candidates()
    assert len(candidates) == 3


def test_candidate_model_and_manufacturer() -> None:
    c = _load_candidates()[0]
    assert c.manufacturer == "Analog Devices"
    assert c.source == "table"
    assert c.model == "ADL5243"


def test_freq_range_is_rawvalue_tuple_in_hz() -> None:
    c = next(x for x in _load_candidates() if x.model == "ADL5243")
    rv = c.raw_params["freq_range"]
    assert rv == RawValue(value=(100000000.0, 4000000000.0), unit="Hz")


def test_missing_scalar_params_are_absent() -> None:
    c = next(x for x in _load_candidates() if x.model == "ADL5243")
    assert "Gain" not in c.raw_params
    assert "Psat" not in c.raw_params


def test_present_scalar_param() -> None:
    c = next(x for x in _load_candidates() if x.model == "ADL5320")
    assert c.raw_params["Gain"] == RawValue(value=13.2, unit="dB")


def test_candidate_url_contains_model() -> None:
    c = _load_candidates()[0]
    assert "analog.com" in c.url
    assert "adl5243" in c.url


def test_all_rf_params_present_for_adh() -> None:
    c = next(x for x in _load_candidates() if x.model == "ADH465S")
    expected_keys = {"freq_range", "Gain", "NF", "P1dB", "Psat", "IP3"}
    assert expected_keys <= set(c.raw_params)


def test_vdd_range_from_min_max_fields() -> None:
    """VDD combines fields 1516 (min) + 1517 (max) into a (min, max) range."""
    c = next(x for x in _load_candidates() if x.model == "ADL5243")
    assert c.raw_params["VDD"] == RawValue(value=(4.75, 5.25), unit="V")


def test_freq_range_stored_in_hz_with_zero_low_edge() -> None:
    """ADH465S is DC-coupled: freq_low '0' must be kept, giving a (0, high) range."""
    c = next(x for x in _load_candidates() if x.model == "ADH465S")
    assert c.raw_params["freq_range"] == RawValue((0.0, 20000000000.0), "Hz")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_invalid_json_raises_adaptererror() -> None:
    with pytest.raises(AdapterError):
        AnalogDevicesAdapter()._parse_json("not valid json {{")


def test_missing_data_array_raises_adaptererror() -> None:
    with pytest.raises(AdapterError):
        AnalogDevicesAdapter()._parse_json('{"categoryId": "3003"}')


# ---------------------------------------------------------------------------
# Inline JSON — edge cases not present in the fixture
# ---------------------------------------------------------------------------

def test_na_and_dash_sentinels_skipped() -> None:
    doc = {"data": [{
        "0": {"value": ["X1"]},
        "279": {"value": ["1000000000"]}, "278": {"value": ["6000000000"]},
        "2930": {"value": ["-"]},      # dash
        "2922": {"value": ["NA"]},     # NA
        "2921": {"value": ["N/A"]},    # N/A
        "2913": {"value": ["12"]},     # valid
    }]}
    c = AnalogDevicesAdapter()._parse_json(json.dumps(doc))[0]
    assert "P1dB" not in c.raw_params
    assert "IP3" not in c.raw_params
    assert "NF" not in c.raw_params
    assert c.raw_params["Gain"] == RawValue(12.0, "dB")


def test_empty_freq_low_drops_range() -> None:
    """freq_low empty but freq_high present -> no freq_range is built."""
    doc = {"data": [{
        "0": {"value": ["X2"]},
        "279": {"value": [""]}, "278": {"value": ["1700000000"]},
        "2922": {"value": ["46"]},
    }]}
    c = AnalogDevicesAdapter()._parse_json(json.dumps(doc))[0]
    assert "freq_range" not in c.raw_params
    assert c.raw_params["IP3"] == RawValue(46.0, "dBm")


def test_bandwidth_fallback_builds_dc_to_bw_range() -> None:
    """A wideband/differential part with only a -3 dB Bandwidth (fid 1519) and no
    279/278 band maps its bandwidth to a (0, BW) freq_range."""
    doc = {"data": [{
        "0": {"value": ["AD8131"]},
        "1519": {"value": ["400000000"]},   # 400 MHz bandwidth, no 279/278
    }]}
    c = AnalogDevicesAdapter()._parse_json(json.dumps(doc))[0]
    assert c.raw_params["freq_range"] == RawValue((0.0, 400000000.0), "Hz")


def test_freq_response_band_takes_precedence_over_bandwidth() -> None:
    """When both 279/278 and 1519 exist (true RF parts), the frequency-response
    band wins; the bandwidth (which merely mirrors the upper edge) is ignored."""
    doc = {"data": [{
        "0": {"value": ["ADL5243"]},
        "279": {"value": ["100000000"]}, "278": {"value": ["4000000000"]},
        "1519": {"value": ["4000000000"]},   # mirrors upper edge -> must be ignored
    }]}
    c = AnalogDevicesAdapter()._parse_json(json.dumps(doc))[0]
    assert c.raw_params["freq_range"] == RawValue((100000000.0, 4000000000.0), "Hz")


def test_part_with_no_rf_fields_yields_empty_params() -> None:
    """A differential-amp-style row with no mapped fields -> empty raw_params."""
    doc = {"data": [{"0": {"value": ["AD8131"]}, "278": {"value": [""]}}]}
    c = AnalogDevicesAdapter()._parse_json(json.dumps(doc))[0]
    assert c.model == "AD8131"
    assert c.raw_params == {}


def test_row_without_model_is_skipped() -> None:
    doc = {"data": [{"279": {"value": ["1000000000"]}}]}   # no field "0"
    assert AnalogDevicesAdapter()._parse_json(json.dumps(doc)) == []


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sentinel", ["", "-", "NA", "N/A", "n/a"])
def test_parse_float_sentinels_return_none(sentinel) -> None:
    assert _parse_float(sentinel) is None


def test_parse_float_none_returns_none() -> None:
    assert _parse_float(None) is None


def test_parse_float_scientific_notation() -> None:
    assert _parse_float("2e-11") == 2e-11
    assert _parse_float("1.7e9") == 1.7e9


def test_parse_float_normal_values() -> None:
    assert _parse_float("25.7") == 25.7
    assert _parse_float("0") == 0.0


def test_cell_value_absent_empty_and_present() -> None:
    assert _cell_value({}, "0") is None
    assert _cell_value({"0": {"value": []}}, "0") is None
    assert _cell_value({"0": {"value": [""]}}, "0") is None
    assert _cell_value({"0": {"value": ["AD8131"]}}, "0") == "AD8131"


# ---------------------------------------------------------------------------
# Datasheet link (derived from the part number; the feed carries none)
# ---------------------------------------------------------------------------

def test_datasheet_url_is_derived_from_the_model() -> None:
    """The feed has no document link at all, so the URL is built from the model.

    Case-1-equivalent: no extra request, since the part number is already in the
    parametric payload. Verified in a browser that this path serves the PDF
    (ADL6346B and HMC1131).
    """
    cand = next(c for c in _load_candidates() if c.model == "ADL5243")
    assert cand.datasheet_url == "https://www.analog.com/en/ADL5243/datasheet"


def test_datasheet_url_keeps_the_model_case_but_product_url_lowercases_it() -> None:
    """The two URLs differ deliberately — the datasheet path is case-sensitive."""
    cand = next(c for c in _load_candidates() if c.model == "ADL5243")
    assert cand.url == "https://www.analog.com/en/products/adl5243.html"
    assert "/ADL5243/" in cand.datasheet_url


def test_every_candidate_carries_a_datasheet_url() -> None:
    for cand in _load_candidates():
        assert cand.datasheet_url and cand.datasheet_url.startswith("https://")
