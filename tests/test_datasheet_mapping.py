"""Tests for rf_finder/datasheet/mapping.py — extractor output -> RawValue.

The final assertions drive the value through the REAL Verifier so the mapping is
proven compatible with verifier.py / parameters.py / units.py / models.py, not
just shaped to look right.
"""

from __future__ import annotations

from rf_finder.datasheet.mapping import to_raw_params
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue
from rf_finder.verifier import verify


def _spec(*constraints: ParamConstraint) -> QuerySpec:
    return QuerySpec(component_type="amplifier", constraints=list(constraints))


def _candidate(raw_params: dict) -> Candidate:
    return Candidate(
        model="ADCA3270", manufacturer="Mini-Circuits",
        url="https://example.com/ADCA3270", raw_params=raw_params, source="datasheet",
    )


# The ADCA3270 spec figures, in the shape extract_rf_parameters produces.
def _spec_obj(**kw):
    base = {"unit": None, "min": None, "typ": None, "max": None,
            "value": None, "condition": None}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Shape selection by comparison rule
# ---------------------------------------------------------------------------

def test_min_comparison_takes_guaranteed_min():
    # Gain (comparison "min"): the guaranteed value is the stated min, preferred
    # over typ/max.
    params = {"Gain": _spec_obj(unit="dB", min=22.0, typ=23.6, max=25.0)}

    raw = to_raw_params(params)

    assert raw["Gain"] == RawValue(value=22.0, unit="dB")


def test_max_comparison_takes_guaranteed_max():
    # NF (comparison "max"): with no stated max, typ is used as the guaranteed
    # value.
    params = {"NF": _spec_obj(unit="dB", typ=3.0)}

    raw = to_raw_params(params)

    assert raw["NF"] == RawValue(value=3.0, unit="dB")


def test_min_comparison_ignores_opposite_end_max():
    # Gain (comparison "min"): a stated max must NOT be borrowed as the
    # guaranteed floor (that would be optimistic). With only max, the parameter
    # is left unresolved so the Verifier reports it UNKNOWN.
    params = {"Gain": _spec_obj(unit="dB", max=25.0)}

    raw = to_raw_params(params)

    assert "Gain" not in raw


def test_max_comparison_ignores_opposite_end_min():
    # NF (comparison "max"): a stated min must NOT be borrowed as the guaranteed
    # ceiling. With only min, the parameter is left unresolved -> UNKNOWN.
    params = {"NF": _spec_obj(unit="dB", min=1.0)}

    raw = to_raw_params(params)

    assert "NF" not in raw


def test_contains_range_becomes_low_high_tuple():
    params = {"Temperature": _spec_obj(unit="C", min=-30, max=110)}

    raw = to_raw_params(params)

    assert raw["Temperature"] == RawValue(value=(-30.0, 110.0), unit="degC")


import pytest


@pytest.mark.parametrize(
    "spelling",
    ["Celsius", "degree Celsius", "degrees Celsius", "deg C", "degC",
     "°C", "C", "centigrade"],
)
def test_any_celsius_spelling_reconciles_to_degc(spelling):
    # The LLM emits many free-form Celsius spellings (all live-observed variants);
    # every one must map to canonical "degC", not pass through (which
    # units.to_canonical cannot convert -> the ValueError that dropped every
    # enriched candidate).
    params = {"Temperature": _spec_obj(unit=spelling, min=-40, max=85)}

    raw = to_raw_params(params)

    assert raw["Temperature"] == RawValue(value=(-40.0, 85.0), unit="degC")


def test_fahrenheit_unit_maps_to_degf_and_verifies_via_conversion():
    # A Fahrenheit datasheet: mapping reconciles the spelling to "degF", then the
    # REAL verifier converts degF -> degC. -40..185 degF = -40..85 degC, which
    # covers a requested -20..70 degC band -> PASS. Proves the two layers compose.
    params = {"Temperature": _spec_obj(unit="Fahrenheit", min=-40, max=185)}

    raw = to_raw_params(params)
    assert raw["Temperature"] == RawValue(value=(-40.0, 185.0), unit="degF")

    spec = _spec(ParamConstraint("Temperature", "contains", None, (-20.0, 70.0), "degC"))
    result = verify(spec, _candidate(raw))
    assert result.verdicts[0].status == "PASS"


def test_contains_discrete_list_stays_a_list():
    params = {"VDD": _spec_obj(unit="V", value=[3, 5, 8])}

    raw = to_raw_params(params)

    assert raw["VDD"] == RawValue(value=[3.0, 5.0, 8.0], unit="V")


# ---------------------------------------------------------------------------
# Non-numeric strings parsed to numbers
# ---------------------------------------------------------------------------

def test_dimension_string_parses_to_largest_dimension():
    # length/width (comparison "max"): from a "9.00 x 8.00 mm" string each takes
    # the worst-case (largest) figure, 9.0 mm — identical max-scalar handling to NF.
    for name in ("length", "width"):
        params = {name: _spec_obj(unit="mm", value="9.00 x 8.00 mm")}

        raw = to_raw_params(params)

        assert raw[name] == RawValue(value=9.0, unit="mm")


def test_length_unit_aliases_are_reconciled():
    # Variant spellings / plurals / symbols / CASE of the size units normalise to
    # the canonical mm / cm / inch / mil (the Verifier then converts them to mm).
    cases = {
        "millimeter": "mm", "millimetres": "mm", "MM": "mm", " Mm ": "mm",
        "centimeter": "cm", "centimetres": "cm", "CM": "cm",
        "inches": "inch", "in": "inch", '"': "inch", "INCH": "inch",
        "mils": "mil", "thou": "mil", "THOU": "mil",
    }
    for stated, canonical in cases.items():
        raw = to_raw_params({"length": _spec_obj(unit=stated, typ=5.0)})
        assert raw["length"] == RawValue(value=5.0, unit=canonical)


def test_msl_string_parses_to_number_with_canonical_unit():
    params = {"MSL": _spec_obj(value="3")}

    raw = to_raw_params(params)

    assert raw["MSL"] == RawValue(value=3.0, unit="")


# ---------------------------------------------------------------------------
# Missing unit: fill the canonical unit only when it is unambiguous
# ---------------------------------------------------------------------------

def test_single_unit_missing_unit_fills_canonical():
    # Gain accepts only dB, so a value with no unit unambiguously means dB.
    params = {"Gain": _spec_obj(min=22.0)}  # unit omitted

    raw = to_raw_params(params)

    assert raw["Gain"] == RawValue(value=22.0, unit="dB")


def test_multi_unit_missing_unit_is_not_guessed():
    # freq_range accepts GHz/MHz — a value with no unit is ambiguous, so the
    # mapping must NOT assume the canonical GHz; it omits the parameter (UNKNOWN)
    # rather than risk a 1000x error.
    params = {"freq_range": _spec_obj(min=2.0, max=6.0)}  # unit omitted

    raw = to_raw_params(params)

    assert "freq_range" not in raw


# ---------------------------------------------------------------------------
# Skipping
# ---------------------------------------------------------------------------

def test_not_found_and_unknown_names_are_skipped():
    params = {"Gain": None, "not_an_ontology_param": _spec_obj(typ=5)}

    assert to_raw_params(params) == {}


# ---------------------------------------------------------------------------
# End-to-end through the real Verifier
# ---------------------------------------------------------------------------

def test_mapped_params_verify_against_real_verifier():
    params = {
        "Gain": _spec_obj(unit="dB", min=22.0, typ=23.6, max=25.0),
        "NF": _spec_obj(unit="dB", typ=3.0),
        "Temperature": _spec_obj(unit="C", min=-30, max=110),
        "length": _spec_obj(unit="mm", value="9.00 x 8.00 mm"),
    }
    candidate = _candidate(to_raw_params(params))

    spec = _spec(
        ParamConstraint("Gain", "min", 20.0, None, "dB"),          # 22 >= 20 -> PASS
        ParamConstraint("NF", "max", 4.0, None, "dB"),             # 3 <= 4 -> PASS
        ParamConstraint("Temperature", "contains", None, (0.0, 85.0), "degC"),  # covers -> PASS
        ParamConstraint("length", "max", 10.0, None, "mm"),        # 9 <= 10 -> PASS
    )

    result = verify(spec, candidate)

    assert [v.status for v in result.verdicts] == ["PASS", "PASS", "PASS", "PASS"]
    assert result.overall == "match"
    assert result.confidence == "datasheet"


def test_mapped_gain_can_fail_when_below_requirement():
    candidate = _candidate(
        to_raw_params({"Gain": _spec_obj(unit="dB", min=22.0, typ=23.6, max=25.0)})
    )
    spec = _spec(ParamConstraint("Gain", "min", 24.0, None, "dB"))  # 22 < 24 -> FAIL

    result = verify(spec, candidate)

    assert result.verdicts[0].status == "FAIL"
    assert result.overall == "fail"
