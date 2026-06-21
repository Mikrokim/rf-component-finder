"""Tests for rf_finder/models.py — T2 Data Models."""

import pytest

from rf_finder.models import (
    Candidate,
    ParamConstraint,
    ParamVerdict,
    QuerySpec,
    RawValue,
    VerifiedCandidate,
)


# ---------------------------------------------------------------------------
# ParamConstraint — invariant enforcement
# ---------------------------------------------------------------------------

class TestParamConstraintInvariant:
    """Both-None and both-set are rejected; exactly-one cases are accepted."""

    def test_value_only_is_valid(self):
        pc = ParamConstraint(
            canonical_name="P1dB",
            comparison="min",
            value=20.0,
            range=None,
            unit="dBm",
        )
        assert pc.value == 20.0
        assert pc.range is None

    def test_range_only_is_valid(self):
        pc = ParamConstraint(
            canonical_name="freq_range",
            comparison="contains",
            value=None,
            range=(2.0, 6.0),
            unit="GHz",
        )
        assert pc.range == (2.0, 6.0)
        assert pc.value is None

    def test_both_none_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            ParamConstraint(
                canonical_name="P1dB",
                comparison="min",
                value=None,
                range=None,
                unit="dBm",
            )

    def test_both_set_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            ParamConstraint(
                canonical_name="P1dB",
                comparison="min",
                value=20.0,
                range=(1.0, 3.0),
                unit="dBm",
            )

    def test_error_message_shows_values(self):
        with pytest.raises(ValueError, match="value=None"):
            ParamConstraint(
                canonical_name="NF",
                comparison="max",
                value=None,
                range=None,
                unit="dB",
            )

    def test_frozen(self):
        pc = ParamConstraint(
            canonical_name="gain", comparison="min", value=10.0, range=None, unit="dB"
        )
        with pytest.raises((AttributeError, TypeError)):
            pc.value = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# QuerySpec
# ---------------------------------------------------------------------------

class TestQuerySpec:
    def test_basic_construction(self):
        pc = ParamConstraint(
            canonical_name="gain", comparison="min", value=20.0, range=None, unit="dB"
        )
        qs = QuerySpec(component_type="amplifier", constraints=[pc])
        assert qs.component_type == "amplifier"
        assert len(qs.constraints) == 1

    def test_empty_constraints_is_valid(self):
        qs = QuerySpec(component_type="filter", constraints=[])
        assert qs.constraints == []

    def test_frozen(self):
        qs = QuerySpec(component_type="amplifier", constraints=[])
        with pytest.raises((AttributeError, TypeError)):
            qs.component_type = "filter"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RawValue
# ---------------------------------------------------------------------------

class TestRawValue:
    def test_scalar_value(self):
        rv = RawValue(value=2400.0, unit="MHz")
        assert rv.value == 2400.0
        assert rv.unit == "MHz"

    def test_range_value(self):
        rv = RawValue(value=(2000.0, 6000.0), unit="MHz")
        assert rv.value == (2000.0, 6000.0)

    def test_frozen(self):
        rv = RawValue(value=1.0, unit="GHz")
        with pytest.raises((AttributeError, TypeError)):
            rv.unit = "MHz"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------

class TestCandidate:
    def _make(self) -> Candidate:
        return Candidate(
            model="ZX60-83LN-S+",
            manufacturer="Mini-Circuits",
            url="https://example.com/ZX60-83LN-S+",
            raw_params={
                "freq_range": RawValue(value=(500.0, 8000.0), unit="MHz"),
                "gain": RawValue(value=20.0, unit="dB"),
            },
            source="table",
        )

    def test_fields(self):
        c = self._make()
        assert c.model == "ZX60-83LN-S+"
        assert c.manufacturer == "Mini-Circuits"
        assert c.source == "table"
        assert "freq_range" in c.raw_params

    def test_frozen(self):
        c = self._make()
        with pytest.raises((AttributeError, TypeError)):
            c.model = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ParamVerdict
# ---------------------------------------------------------------------------

class TestParamVerdict:
    def _constraint(self) -> ParamConstraint:
        return ParamConstraint(
            canonical_name="gain", comparison="min", value=20.0, range=None, unit="dB"
        )

    def test_pass_verdict(self):
        found = RawValue(value=22.0, unit="dB")
        pv = ParamVerdict(
            canonical_name="gain",
            status="PASS",
            required=self._constraint(),
            found=found,
        )
        assert pv.status == "PASS"
        assert pv.found is found

    def test_unknown_verdict_none_found(self):
        pv = ParamVerdict(
            canonical_name="NF",
            status="UNKNOWN",
            required=ParamConstraint(
                canonical_name="NF", comparison="max", value=3.0, range=None, unit="dB"
            ),
            found=None,
        )
        assert pv.found is None
        assert pv.status == "UNKNOWN"

    def test_frozen(self):
        pv = ParamVerdict(
            canonical_name="gain",
            status="FAIL",
            required=self._constraint(),
            found=None,
        )
        with pytest.raises((AttributeError, TypeError)):
            pv.status = "PASS"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# VerifiedCandidate
# ---------------------------------------------------------------------------

class TestVerifiedCandidate:
    def _candidate(self) -> Candidate:
        return Candidate(
            model="M1",
            manufacturer="ACME",
            url="https://example.com/M1",
            raw_params={},
            source="table",
        )

    def _constraint(self, name: str = "gain") -> ParamConstraint:
        return ParamConstraint(
            canonical_name=name, comparison="min", value=10.0, range=None, unit="dB"
        )

    def test_match_overall(self):
        verdict = ParamVerdict(
            canonical_name="gain",
            status="PASS",
            required=self._constraint(),
            found=RawValue(value=15.0, unit="dB"),
        )
        vc = VerifiedCandidate(
            candidate=self._candidate(),
            verdicts=[verdict],
            overall="match",
            confidence="table",
        )
        assert vc.overall == "match"
        assert vc.confidence == "table"

    def test_fail_overall(self):
        verdict = ParamVerdict(
            canonical_name="gain",
            status="FAIL",
            required=self._constraint(),
            found=RawValue(value=5.0, unit="dB"),
        )
        vc = VerifiedCandidate(
            candidate=self._candidate(),
            verdicts=[verdict],
            overall="fail",
            confidence="table",
        )
        assert vc.overall == "fail"

    def test_partial_overall(self):
        verdict = ParamVerdict(
            canonical_name="NF",
            status="UNKNOWN",
            required=self._constraint("NF"),
            found=None,
        )
        vc = VerifiedCandidate(
            candidate=self._candidate(),
            verdicts=[verdict],
            overall="partial",
            confidence="unknown",
        )
        assert vc.overall == "partial"
        assert vc.confidence == "unknown"

    def test_frozen(self):
        vc = VerifiedCandidate(
            candidate=self._candidate(),
            verdicts=[],
            overall="match",
            confidence="table",
        )
        with pytest.raises((AttributeError, TypeError)):
            vc.overall = "fail"  # type: ignore[misc]
