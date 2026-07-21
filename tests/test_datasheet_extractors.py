"""Tests for the deterministic code extractors (rf_finder/datasheet/code_extractors).

Two honestly-separated groups:

* REGRESSION — the datasheets the regex was BUILT on. Passing here only proves we
  have not broken known-good behaviour; it does NOT prove generalisation.
* HELD-OUT — datasheets the regex was never tuned on (verified correct with zero
  regex changes). Passing here is the real generalisation signal. Grow this set.

Plus plain-text unit scenarios from the spec that need no PDF.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rf_finder.datasheet import (
    datasheet_text_from_pdf,
    msl_level,
    size_dims,
    temp_range,
)

PDFS = Path(__file__).resolve().parent.parent / "evals" / "pdfs"

# name, TEMP(min,max), SIZE(a,b), MSL — all values verified against source.
REGRESSION = [
    ("grf2111", (-40, 105), (1.5, 1.5), "1"),
    ("adca3270", (-30, 110), (9.0, 8.0), "3"),
    ("am06013033wm", (-40, 85), (5.0, 5.0), None),
    ("cmpa1e1f060d", (-40, 85), (4530.0, 6090.0), None),
]
HELD_OUT = [
    ("cha2292", (-40, 85), (2.32, 1.23), None),      # UMS/OMMIC, MSL absent
    ("max22707", (-40, 125), (3.0, 3.0), None),      # Maxim/ADI, MSL absent
    ("cmd240c4", (-40, 85), (4.0, 4.0), "1"),        # Custom MMIC, MSL present
    ("qpl7420", (-40, 100), (3.0, 3.0), "2"),        # Qorvo, MSL present, -40/100
]


def _load(name: str) -> str:
    pdf = PDFS / f"{name}.pdf"
    if not pdf.exists():
        pytest.skip(f"datasheet {pdf} not available")
    return datasheet_text_from_pdf(str(pdf))


def _cases(group, label):
    # the group (regression vs held-out) is encoded in the test id, visible in -v
    return [pytest.param(c, id=f"{label}:{c[0]}") for c in group]


ALL_CASES = _cases(REGRESSION, "regression") + _cases(HELD_OUT, "held_out")


@pytest.fixture(params=ALL_CASES)
def case(request):
    name, temp, size, msl = request.param
    return name, _load(name), temp, size, msl


def test_temperature(case):
    _, text, temp, _, _ = case
    assert temp_range(text) == temp


def test_size(case):
    _, text, _, size, _ = case
    assert size_dims(text) == size


def test_msl(case):
    _, text, _, _, msl = case
    assert msl_level(text) == msl


# --- plain-text unit scenarios (spec) --------------------------------------

def test_temp_excludes_storage():
    t = "Operating Temperature -40 to +85 °C   Storage Temperature -55 to +135 °C"
    assert temp_range(t) == (-40, 85)


def test_temp_column_format_without_to():
    assert temp_range("Operating Temperature (package base). TPKG BASE -40 105 °C") == (-40, 105)


def test_temp_ignores_footnote_superscript():
    assert temp_range("Operating Temperature5 -40°C to +85°C") == (-40, 85)


def test_temp_en_dash_is_minus():
    assert temp_range("Operating temperature –55 °C to +85 °C") == (-55, 85)


def test_temp_bare_range_fallback_when_not_storage():
    assert temp_range("Gain 20 dB. Temperature Range -40°C to +125°C 16-Lead LFCSP") == (-40, 125)


def test_size_rejects_mttf_scientific_notation():
    assert size_dims("These conditions ensure MTTF > 1 x 106 hours.") is None


def test_size_pin_count_pad_is_not_a_bond_pad():
    assert size_dims("24 Pad 5 x 3 mm Laminate Package") == (5.0, 3.0)


def test_msl_skips_reflow_temperature():
    assert msl_level("Peak Reflow (Moisture Sensitivity Level 260°C) additional (MSL) 3 info") == "3"


def test_msl_absent_is_none():
    assert msl_level("This part has no moisture rating stated.") is None
