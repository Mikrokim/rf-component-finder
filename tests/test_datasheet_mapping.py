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
    # Gain (comparison "min"): guaranteed value is the smallest stated figure.
    params = {"Gain": _spec_obj(unit="dB", min=22.0, typ=23.6, max=25.0)}

    raw = to_raw_params(params)

    assert raw["Gain"] == RawValue(value=22.0, unit="dB")


def test_max_comparison_takes_guaranteed_max():
    # NF (comparison "max"): guaranteed value is the largest stated figure.
    params = {"NF": _spec_obj(unit="dB", typ=3.0)}

    raw = to_raw_params(params)

    assert raw["NF"] == RawValue(value=3.0, unit="dB")


def test_contains_range_becomes_low_high_tuple():
    params = {"Temperature": _spec_obj(unit="C", min=-30, max=110)}

    raw = to_raw_params(params)

    assert raw["Temperature"] == RawValue(value=(-30.0, 110.0), unit="degC")


def test_contains_discrete_list_stays_a_list():
    params = {"VDD": _spec_obj(unit="V", value=[3, 5, 8])}

    raw = to_raw_params(params)

    assert raw["VDD"] == RawValue(value=[3.0, 5.0, 8.0], unit="V")


# ---------------------------------------------------------------------------
# Non-numeric strings parsed to numbers
# ---------------------------------------------------------------------------

def test_size_string_parses_to_largest_dimension():
    # Size (comparison "max"): "9.00 x 8.00 mm" -> worst case is the 9.0 mm side.
    params = {"Size": _spec_obj(unit="mm", value="9.00 x 8.00 mm")}

    raw = to_raw_params(params)

    assert raw["Size"] == RawValue(value=9.0, unit="mm")


def test_msl_string_parses_to_number_with_canonical_unit():
    params = {"MSL": _spec_obj(value="3")}

    raw = to_raw_params(params)

    assert raw["MSL"] == RawValue(value=3.0, unit="")


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
        "Size": _spec_obj(unit="mm", value="9.00 x 8.00 mm"),
    }
    candidate = _candidate(to_raw_params(params))

    spec = _spec(
        ParamConstraint("Gain", "min", 20.0, None, "dB"),          # 22 >= 20 -> PASS
        ParamConstraint("NF", "max", 4.0, None, "dB"),             # 3 <= 4 -> PASS
        ParamConstraint("Temperature", "contains", None, (0.0, 85.0), "degC"),  # covers -> PASS
        ParamConstraint("Size", "max", 10.0, None, "mm"),          # 9 <= 10 -> PASS
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
