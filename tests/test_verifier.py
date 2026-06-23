"""Tests for rf_finder/verifier.py — T6 Verifier (REQ-4).

Covers the full comparison matrix specified in design.md §7 and the T6 task.
"""

from __future__ import annotations

import pytest

from rf_finder.models import (
    Candidate,
    ParamConstraint,
    ParamVerdict,
    QuerySpec,
    RawValue,
    VerifiedCandidate,
)
from rf_finder.verifier import verify


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(
    raw_params: dict[str, RawValue],
    source: str = "table",
) -> Candidate:
    return Candidate(
        model="TEST-001",
        manufacturer="Acme RF",
        url="https://example.com/TEST-001",
        raw_params=raw_params,
        source=source,
    )


def _make_spec(*constraints: ParamConstraint) -> QuerySpec:
    return QuerySpec(component_type="amplifier", constraints=list(constraints))


def _scalar_constraint(
    name: str,
    comparison: str,
    value: float,
    unit: str,
) -> ParamConstraint:
    return ParamConstraint(
        canonical_name=name,
        comparison=comparison,
        value=value,
        range=None,
        unit=unit,
    )


def _range_constraint(
    name: str,
    low: float,
    high: float,
    unit: str,
) -> ParamConstraint:
    return ParamConstraint(
        canonical_name=name,
        comparison="contains",
        value=None,
        range=(low, high),
        unit=unit,
    )


# ---------------------------------------------------------------------------
# 1. min comparison — PASS (candidate value >= required)
# ---------------------------------------------------------------------------

class TestMinComparison:
    def test_min_pass(self):
        """Candidate P1dB 30 dBm >= required 26 dBm → PASS."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        cand = _make_candidate({"P1dB": RawValue(30.0, "dBm")})
        result = verify(spec, cand)
        verdict = result.verdicts[0]
        assert verdict.status == "PASS"

    def test_min_pass_equal(self):
        """Candidate P1dB exactly equal to required → PASS (boundary)."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        cand = _make_candidate({"P1dB": RawValue(26.0, "dBm")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "PASS"

    # 2. min comparison — FAIL
    def test_min_fail(self):
        """Candidate P1dB 20 dBm < required 26 dBm → FAIL."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        cand = _make_candidate({"P1dB": RawValue(20.0, "dBm")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "FAIL"


# ---------------------------------------------------------------------------
# 3–4. max comparison
# ---------------------------------------------------------------------------

class TestMaxComparison:
    def test_max_pass(self):
        """Candidate NF 2 dB <= required 3 dB → PASS."""
        spec = _make_spec(_scalar_constraint("NF", "max", 3.0, "dB"))
        cand = _make_candidate({"NF": RawValue(2.0, "dB")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "PASS"

    def test_max_pass_equal(self):
        """Candidate NF exactly at required ceiling → PASS (boundary)."""
        spec = _make_spec(_scalar_constraint("NF", "max", 3.0, "dB"))
        cand = _make_candidate({"NF": RawValue(3.0, "dB")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "PASS"

    def test_max_fail(self):
        """Candidate NF 5 dB > required 3 dB → FAIL."""
        spec = _make_spec(_scalar_constraint("NF", "max", 3.0, "dB"))
        cand = _make_candidate({"NF": RawValue(5.0, "dB")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "FAIL"


# ---------------------------------------------------------------------------
# 5–7. contains comparison
# ---------------------------------------------------------------------------

class TestContainsComparison:
    def test_contains_pass(self):
        """Candidate band (1.0, 8.0) GHz fully contains required (2.0, 6.0) GHz → PASS."""
        spec = _make_spec(_range_constraint("freq_range", 2.0, 6.0, "GHz"))
        cand = _make_candidate({"freq_range": RawValue((1.0, 8.0), "GHz")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "PASS"

    def test_contains_fail_low_end_misses(self):
        """Candidate band (3.0, 8.0) GHz does NOT cover low end of (2.0, 6.0) → FAIL."""
        spec = _make_spec(_range_constraint("freq_range", 2.0, 6.0, "GHz"))
        cand = _make_candidate({"freq_range": RawValue((3.0, 8.0), "GHz")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "FAIL"

    def test_contains_fail_high_end_misses(self):
        """Candidate band (1.0, 5.0) GHz does NOT cover high end of (2.0, 6.0) → FAIL."""
        spec = _make_spec(_range_constraint("freq_range", 2.0, 6.0, "GHz"))
        cand = _make_candidate({"freq_range": RawValue((1.0, 5.0), "GHz")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "FAIL"


# ---------------------------------------------------------------------------
# 8. UNKNOWN — param not in candidate.raw_params
# ---------------------------------------------------------------------------

class TestUnknown:
    def test_unknown_status(self):
        """Constraint param absent from candidate → status UNKNOWN, found is None."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        cand = _make_candidate({})   # no params at all
        result = verify(spec, cand)
        verdict = result.verdicts[0]
        assert verdict.status == "UNKNOWN"
        assert verdict.found is None

    # 9. UNKNOWN → overall "partial"
    def test_unknown_yields_partial_overall(self):
        """A single UNKNOWN verdict (no FAILs) → overall == "partial"."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        cand = _make_candidate({})
        result = verify(spec, cand)
        assert result.overall == "partial"


# ---------------------------------------------------------------------------
# 10. Any FAIL → overall "fail" (even if other verdicts PASS)
# ---------------------------------------------------------------------------

class TestOverallDecide:
    def test_fail_dominates_pass(self):
        """PASS + FAIL → overall "fail"."""
        spec = _make_spec(
            _scalar_constraint("Gain", "min", 20.0, "dB"),    # will PASS (30 >= 20)
            _scalar_constraint("P1dB", "min", 30.0, "dBm"),   # will FAIL (20 < 30)
        )
        cand = _make_candidate({
            "Gain": RawValue(30.0, "dB"),
            "P1dB": RawValue(20.0, "dBm"),
        })
        result = verify(spec, cand)
        statuses = [v.status for v in result.verdicts]
        assert "PASS" in statuses
        assert "FAIL" in statuses
        assert result.overall == "fail"

    # 11. All PASS → overall "match"
    def test_all_pass_yields_match(self):
        """All verdicts PASS → overall "match"."""
        spec = _make_spec(
            _scalar_constraint("Gain", "min", 20.0, "dB"),
            _scalar_constraint("NF",   "max", 5.0,  "dB"),
        )
        cand = _make_candidate({
            "Gain": RawValue(25.0, "dB"),
            "NF":   RawValue(3.0,  "dB"),
        })
        result = verify(spec, cand)
        assert all(v.status == "PASS" for v in result.verdicts)
        assert result.overall == "match"

    def test_fail_dominates_unknown(self):
        """FAIL + UNKNOWN → overall "fail" (FAIL beats UNKNOWN)."""
        spec = _make_spec(
            _scalar_constraint("P1dB", "min", 30.0, "dBm"),   # FAIL
            _scalar_constraint("Gain", "min", 20.0, "dB"),    # UNKNOWN
        )
        cand = _make_candidate({"P1dB": RawValue(20.0, "dBm")})
        result = verify(spec, cand)
        assert result.overall == "fail"


# ---------------------------------------------------------------------------
# 12. Unit conversion in contains comparison (MHz candidate vs GHz required)
# ---------------------------------------------------------------------------

class TestUnitConversionInContains:
    def test_mhz_candidate_vs_ghz_required_pass(self):
        """Candidate (2000, 6000) MHz must PASS contains (2.0, 6.0) GHz."""
        spec = _make_spec(_range_constraint("freq_range", 2.0, 6.0, "GHz"))
        cand = _make_candidate({"freq_range": RawValue((2000.0, 6000.0), "MHz")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "PASS"

    def test_mhz_candidate_wider_band_pass(self):
        """Candidate (1000, 8000) MHz → (1.0, 8.0) GHz contains (2.0, 6.0) GHz → PASS."""
        spec = _make_spec(_range_constraint("freq_range", 2.0, 6.0, "GHz"))
        cand = _make_candidate({"freq_range": RawValue((1000.0, 8000.0), "MHz")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "PASS"

    def test_mhz_candidate_narrow_band_fail(self):
        """Candidate (3000, 8000) MHz → (3.0, 8.0) GHz does NOT contain (2.0, 6.0) → FAIL."""
        spec = _make_spec(_range_constraint("freq_range", 2.0, 6.0, "GHz"))
        cand = _make_candidate({"freq_range": RawValue((3000.0, 8000.0), "MHz")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "FAIL"


# ---------------------------------------------------------------------------
# 12b. Non-canonical CONSTRAINT unit (user picks MHz / W) — regression
#      Previously crashed with "Unsupported canonical unit 'MHz'".
# ---------------------------------------------------------------------------

class TestNonCanonicalConstraintUnit:
    def test_mhz_constraint_vs_ghz_candidate_pass(self):
        """User asks for 2000–6000 MHz; candidate (1.0, 8.0) GHz covers it → PASS."""
        spec = _make_spec(_range_constraint("freq_range", 2000.0, 6000.0, "MHz"))
        cand = _make_candidate({"freq_range": RawValue((1.0, 8.0), "GHz")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "PASS"

    def test_mhz_constraint_vs_ghz_candidate_fail(self):
        """User asks for 2000–6000 MHz; candidate (3.0, 5.0) GHz misses both ends → FAIL."""
        spec = _make_spec(_range_constraint("freq_range", 2000.0, 6000.0, "MHz"))
        cand = _make_candidate({"freq_range": RawValue((3.0, 5.0), "GHz")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "FAIL"

    def test_watt_constraint_vs_dbm_candidate_pass(self):
        """User asks P1dB min 0.1 W (= 20 dBm); candidate 25 dBm → PASS."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 0.1, "W"))
        cand = _make_candidate({"P1dB": RawValue(25.0, "dBm")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "PASS"

    def test_watt_constraint_vs_dbm_candidate_fail(self):
        """User asks P1dB min 0.1 W (= 20 dBm); candidate 15 dBm → FAIL."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 0.1, "W"))
        cand = _make_candidate({"P1dB": RawValue(15.0, "dBm")})
        result = verify(spec, cand)
        assert result.verdicts[0].status == "FAIL"


# ---------------------------------------------------------------------------
# 13–14. Confidence from candidate.source
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_confidence_from_table_source(self):
        """candidate.source == "table" → VerifiedCandidate.confidence == "table"."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        cand = _make_candidate({"P1dB": RawValue(30.0, "dBm")}, source="table")
        result = verify(spec, cand)
        assert result.confidence == "table"

    def test_confidence_from_datasheet_source(self):
        """candidate.source == "datasheet" → VerifiedCandidate.confidence == "datasheet"."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        cand = _make_candidate({"P1dB": RawValue(30.0, "dBm")}, source="datasheet")
        result = verify(spec, cand)
        assert result.confidence == "datasheet"

    def test_confidence_unknown_for_unexpected_source(self):
        """Unrecognised candidate.source → VerifiedCandidate.confidence == "unknown"."""
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        # Bypass frozen dataclass type narrowing; models allow str at runtime.
        cand = Candidate(
            model="X",
            manufacturer="Y",
            url="http://example.com",
            raw_params={"P1dB": RawValue(30.0, "dBm")},
            source="scraped",   # not "table" or "datasheet"
        )
        result = verify(spec, cand)
        assert result.confidence == "unknown"


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------

class TestStructure:
    def test_verdict_carries_required_constraint(self):
        """ParamVerdict.required must reference the original ParamConstraint."""
        constraint = _scalar_constraint("P1dB", "min", 26.0, "dBm")
        spec = _make_spec(constraint)
        cand = _make_candidate({"P1dB": RawValue(30.0, "dBm")})
        result = verify(spec, cand)
        assert result.verdicts[0].required is constraint

    def test_verdict_carries_raw_value_on_pass(self):
        """ParamVerdict.found must be the RawValue from candidate on non-UNKNOWN verdict."""
        raw = RawValue(30.0, "dBm")
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        cand = _make_candidate({"P1dB": raw})
        result = verify(spec, cand)
        assert result.verdicts[0].found is raw

    def test_verify_returns_verified_candidate(self):
        spec = _make_spec(_scalar_constraint("P1dB", "min", 26.0, "dBm"))
        cand = _make_candidate({"P1dB": RawValue(30.0, "dBm")})
        result = verify(spec, cand)
        assert isinstance(result, VerifiedCandidate)
        assert result.candidate is cand
