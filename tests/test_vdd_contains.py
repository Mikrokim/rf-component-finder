"""VDD ``contains`` rule: end-to-end from the form through the Verifier.

VDD matching is "the part's supply must COVER what you asked for". The user
enters a single value or a range; the part (from each adapter) is a single
value, a range, or a discrete list of selectable supplies. Matching is one
uniform rule that dispatches on the candidate's shape:

              user SINGLE value V        user RANGE (Qlo, Qhi)
  part single P     V == P               not relevant (fixed V can't cover a band)
  part range (l,h)  l <= V <= h          l <= Qlo and h >= Qhi   (part covers your range)
  part list [..]    V is one option      not relevant (discrete can't cover a band)
"""

from __future__ import annotations

from rf_finder.form.input import collect
from rf_finder.form.schema import build_form
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue
from rf_finder.verifier import verify


def _query(low: float, high: float) -> ParamConstraint:
    """A VDD query: a single value is (v, v); a range is (low, high)."""
    return ParamConstraint(
        canonical_name="VDD", comparison="contains", value=None,
        range=(low, high), unit="V",
    )


def _status(query: ParamConstraint, part_vdd) -> str:
    cand = Candidate(
        model="M", manufacturer="Mfr", url="u",
        raw_params={"VDD": RawValue(value=part_vdd, unit="V")}, source="table",
    )
    spec = QuerySpec(component_type="amplifier", constraints=[query])
    return next(v.status for v in verify(spec, cand).verdicts if v.canonical_name == "VDD")


# --- User single value ------------------------------------------------------
def test_single_vs_part_single_exact():
    assert _status(_query(8, 8), (8.0, 8.0)) == "PASS"     # exact
    assert _status(_query(8, 8), (24.0, 24.0)) == "FAIL"   # different

def test_single_vs_part_range_within():
    assert _status(_query(8, 8), (5.0, 10.0)) == "PASS"    # 8 within 5-10
    assert _status(_query(8, 8), (9.0, 15.0)) == "FAIL"    # 8 below 9-15

def test_single_vs_part_discrete_option():
    assert _status(_query(5, 5), [3.0, 5.0, 8.0]) == "PASS"   # 5 is an option
    assert _status(_query(4, 4), [3.0, 5.0, 8.0]) == "FAIL"   # 4 is not offered


# --- User range -------------------------------------------------------------
def test_range_vs_part_single_not_relevant():
    # A fixed single voltage cannot cover a whole requested range.
    assert _status(_query(22, 26), (24.0, 24.0)) == "FAIL"

def test_range_vs_part_range_contained():
    assert _status(_query(22, 26), (18.0, 26.0)) == "PASS"   # covers 22-26
    assert _status(_query(22, 26), (20.0, 30.0)) == "PASS"   # covers 22-26
    assert _status(_query(22, 26), (23.0, 25.0)) == "FAIL"   # doesn't cover all
    assert _status(_query(22, 26), (5.0, 10.0)) == "FAIL"    # disjoint

def test_range_vs_part_discrete_not_relevant():
    # Discrete selectable voltages can't cover a continuous requested range,
    # even when an option falls inside it.
    assert _status(_query(4, 6), [3.0, 5.0, 8.0]) == "FAIL"


# --- Safety net: a stray bare float must not crash the search ---------------
def test_bare_float_candidate_is_coerced():
    assert _status(_query(8, 8), 8.0) == "PASS"
    assert _status(_query(22, 26), 24.0) == "FAIL"


# --- End-to-end: the form builds the right VDD constraint -------------------
def _vdd_constraint(answers: dict[str, str]) -> ParamConstraint | None:
    spec = collect(build_form("amplifier"), answers=answers)
    return next((c for c in spec.constraints if c.canonical_name == "VDD"), None)


def test_form_single_value_becomes_point():
    # One entry (either box) → the point (v, v); no open-ended ±inf.
    c = _vdd_constraint({"VDD.min": "8"})
    assert c is not None and c.comparison == "contains" and c.range == (8.0, 8.0)
    c2 = _vdd_constraint({"VDD.max": "8"})
    assert c2 is not None and c2.range == (8.0, 8.0)

def test_form_range_kept_as_range():
    c = _vdd_constraint({"VDD.min": "22", "VDD.max": "26"})
    assert c is not None and c.comparison == "contains" and c.range == (22.0, 26.0)

def test_form_blank_vdd_is_skipped():
    assert _vdd_constraint({}) is None
