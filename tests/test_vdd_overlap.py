"""VDD `overlap` rule: end-to-end from the form through the Verifier.

VDD models "which supply voltage can I provide" (the query) against "which
voltages the part accepts" (the candidate). A match needs the two to INTERSECT,
not for the candidate to cover the whole requested band. These tests pin that
semantic, the one-sided (MIN-only / MAX-only) queries it enables, all four site
value shapes, and two regressions the old `contains` rule got wrong.
"""

from __future__ import annotations

import math

from rf_finder.form.input import collect
from rf_finder.form.schema import build_form
from rf_finder.models import Candidate, ParamConstraint, QuerySpec, RawValue
from rf_finder.verifier import verify

_INF = math.inf


def _overlap_constraint(low: float, high: float) -> ParamConstraint:
    return ParamConstraint(
        canonical_name="VDD", comparison="overlap", value=None,
        range=(low, high), unit="V",
    )


def _candidate(vdd) -> Candidate:
    return Candidate(
        model="M", manufacturer="Mfr", url="u",
        raw_params={"VDD": RawValue(value=vdd, unit="V")}, source="table",
    )


def _vdd_status(constraint: ParamConstraint, vdd) -> str:
    spec = QuerySpec(component_type="amplifier", constraints=[constraint])
    verified = verify(spec, _candidate(vdd))
    return next(v.status for v in verified.verdicts if v.canonical_name == "VDD")


# --- The overlap semantic on an interval candidate --------------------------
def test_interval_overlap_passes_on_intersection():
    # Part runs 3-5 V; I can supply 4.5-5.5 V. They intersect at ~5 V -> PASS.
    assert _vdd_status(_overlap_constraint(4.5, 5.5), (3.0, 5.0)) == "PASS"


def test_interval_no_overlap_fails():
    # Part runs 3-5 V; I can only supply 8-10 V. No shared voltage -> FAIL.
    assert _vdd_status(_overlap_constraint(8.0, 10.0), (3.0, 5.0)) == "FAIL"


def test_single_value_candidate_inside_query():
    # Part fixed at 8 V ((8,8)); query 0-10 covers it -> PASS.
    assert _vdd_status(_overlap_constraint(0.0, 10.0), (8.0, 8.0)) == "PASS"


# --- One-sided queries (the feature the user asked for) ---------------------
def test_max_only_query():
    # "VDD at most 10" -> (-inf, 10). A 3-5 part overlaps -> PASS; a 12-15 fails.
    assert _vdd_status(_overlap_constraint(-_INF, 10.0), (3.0, 5.0)) == "PASS"
    assert _vdd_status(_overlap_constraint(-_INF, 10.0), (12.0, 15.0)) == "FAIL"


def test_min_only_query():
    # "VDD at least 12" -> (12, inf). A 12-15 part overlaps -> PASS; a 4 V fails.
    assert _vdd_status(_overlap_constraint(12.0, _INF), (12.0, 15.0)) == "PASS"
    assert _vdd_status(_overlap_constraint(12.0, _INF), (4.0, 4.0)) == "FAIL"


# --- Discrete-list candidate under overlap ----------------------------------
def test_discrete_list_option_in_band():
    # Supports {3,5,8}; query 4-6 -> option 5 lies inside -> PASS.
    assert _vdd_status(_overlap_constraint(4.0, 6.0), [3.0, 5.0, 8.0]) == "PASS"


def test_discrete_list_no_option_in_band():
    # Supports {3,5,8}; query 6-7 -> no option inside -> FAIL (4 V gap is real).
    assert _vdd_status(_overlap_constraint(6.0, 7.0), [3.0, 5.0, 8.0]) == "FAIL"


# --- Safety net: a stray bare float must not crash the search ---------------
def test_bare_float_candidate_is_coerced():
    assert _vdd_status(_overlap_constraint(0.0, 10.0), 8.0) == "PASS"


# --- Regression: MIN=0 must NOT mean "must run at 0 V" ----------------------
def test_min_zero_is_not_a_trap():
    # The old contains rule FAILED a 3-5 V part here (it can't cover 0 V).
    # Under overlap, 0-10 simply means "I can supply 0..10", which overlaps 3-5.
    assert _vdd_status(_overlap_constraint(0.0, 10.0), (3.0, 5.0)) == "PASS"


# --- End-to-end: the form builds an overlap constraint ----------------------
def _vdd_constraint_from_form(answers: dict[str, str]) -> ParamConstraint | None:
    spec = collect(build_form("amplifier"), answers=answers)
    return next((c for c in spec.constraints if c.canonical_name == "VDD"), None)


def test_form_two_sided_builds_overlap():
    c = _vdd_constraint_from_form({"VDD.min": "4.5", "VDD.max": "5.5"})
    assert c is not None
    assert c.comparison == "overlap"
    assert c.range == (4.5, 5.5)


def test_form_min_only_allowed_and_open_on_the_max_side():
    c = _vdd_constraint_from_form({"VDD.min": "12"})
    assert c is not None and c.comparison == "overlap"
    assert c.range == (12.0, _INF)


def test_form_max_only_allowed_and_open_on_the_min_side():
    c = _vdd_constraint_from_form({"VDD.max": "10"})
    assert c is not None and c.comparison == "overlap"
    assert c.range == (-_INF, 10.0)


def test_form_blank_vdd_is_skipped():
    assert _vdd_constraint_from_form({}) is None
