"""Tests for rf_finder/form — T5 Form input (REQ-1.1, REQ-1.4–1.7)."""

import pytest

from rf_finder.models import ParamConstraint, QuerySpec
from rf_finder.form import Field, FormSchema, build_form, collect


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _amplifier_schema() -> FormSchema:
    return build_form("amplifier")


# ---------------------------------------------------------------------------
# 1. build_form — schema structure
# ---------------------------------------------------------------------------

class TestBuildForm:
    def test_amplifier_has_exactly_six_fields(self):
        schema = _amplifier_schema()
        assert len(schema.fields) == 6

    def test_component_type_stored_on_schema(self):
        schema = _amplifier_schema()
        assert schema.component_type == "amplifier"

    def test_contains_fields_come_first(self):
        schema = _amplifier_schema()
        # freq_range (contains) must be first
        assert schema.fields[0].canonical_name == "freq_range"
        assert schema.fields[0].comparison == "contains"

    def test_all_remaining_fields_are_scalar(self):
        schema = _amplifier_schema()
        for field in schema.fields[1:]:
            assert field.comparison != "contains"

    def test_unknown_component_type_raises_value_error(self):
        with pytest.raises(ValueError, match="unknown_type"):
            build_form("unknown_type")

    def test_field_units_canonical_first(self):
        schema = _amplifier_schema()
        freq_field = schema.fields[0]
        assert freq_field.units[0] == freq_field.canonical_unit

    def test_field_label_populated(self):
        schema = _amplifier_schema()
        for field in schema.fields:
            assert field.label, f"Field {field.canonical_name!r} has empty label"

    def test_returns_form_schema_instance(self):
        schema = _amplifier_schema()
        assert isinstance(schema, FormSchema)

    def test_fields_are_field_instances(self):
        schema = _amplifier_schema()
        for field in schema.fields:
            assert isinstance(field, Field)


# ---------------------------------------------------------------------------
# 2. collect — TTY seam (answers dict)
# ---------------------------------------------------------------------------

class TestCollectKeystone:
    """§5.2 worked example: amplifier, freq 2–6 GHz, P1dB 26 dBm, rest empty."""

    def test_keystone_exact_query_spec(self):
        schema = _amplifier_schema()
        answers = {
            "freq_range.min": "2",
            "freq_range.max": "6",
            "freq_range.unit": "GHz",
            "P1dB.value": "26",
            "P1dB.unit": "dBm",
        }
        result = collect(schema, answers=answers)

        expected = QuerySpec(
            component_type="amplifier",
            constraints=[
                ParamConstraint(
                    canonical_name="freq_range",
                    comparison="contains",
                    value=None,
                    range=(2.0, 6.0),
                    unit="GHz",
                ),
                ParamConstraint(
                    canonical_name="P1dB",
                    comparison="min",
                    value=26.0,
                    range=None,
                    unit="dBm",
                ),
            ],
        )
        assert result == expected


class TestCollectAllEmpty:
    def test_all_fields_empty_returns_empty_constraints(self):
        schema = _amplifier_schema()
        result = collect(schema, answers={})
        expected = QuerySpec(component_type="amplifier", constraints=[])
        assert result == expected


class TestCollectValidation:
    def test_freq_range_min_greater_than_max_raises_value_error(self):
        schema = _amplifier_schema()
        answers = {
            "freq_range.min": "6",
            "freq_range.max": "2",
            "freq_range.unit": "GHz",
        }
        with pytest.raises(ValueError):
            collect(schema, answers=answers)

    def test_non_numeric_value_raises_value_error(self):
        schema = _amplifier_schema()
        answers = {
            "P1dB.value": "notanumber",
            "P1dB.unit": "dBm",
        }
        with pytest.raises(ValueError):
            collect(schema, answers=answers)

    def test_non_numeric_freq_min_raises_value_error(self):
        schema = _amplifier_schema()
        answers = {
            "freq_range.min": "abc",
            "freq_range.max": "6",
            "freq_range.unit": "GHz",
        }
        with pytest.raises(ValueError):
            collect(schema, answers=answers)

    def test_invalid_unit_raises_value_error(self):
        schema = _amplifier_schema()
        answers = {
            "P1dB.value": "26",
            "P1dB.unit": "Watts",  # not in field.units
        }
        with pytest.raises(ValueError):
            collect(schema, answers=answers)


class TestCollectUnitStored:
    def test_unit_on_constraint_matches_answer(self):
        schema = _amplifier_schema()
        answers = {
            "freq_range.min": "500",
            "freq_range.max": "3000",
            "freq_range.unit": "MHz",
        }
        result = collect(schema, answers=answers)
        assert len(result.constraints) == 1
        assert result.constraints[0].unit == "MHz"

    def test_scalar_unit_on_constraint_matches_answer(self):
        schema = _amplifier_schema()
        answers = {
            "P1dB.value": "0.4",
            "P1dB.unit": "W",
        }
        result = collect(schema, answers=answers)
        assert len(result.constraints) == 1
        assert result.constraints[0].unit == "W"

    def test_unit_not_converted_to_canonical(self):
        """The form stores the user's chosen unit as-is; Verifier normalizes later."""
        schema = _amplifier_schema()
        answers = {
            "freq_range.min": "2000",
            "freq_range.max": "6000",
            "freq_range.unit": "MHz",
        }
        result = collect(schema, answers=answers)
        constraint = result.constraints[0]
        assert constraint.unit == "MHz"
        assert constraint.range == (2000.0, 6000.0)


class TestCollectReturnType:
    def test_returns_query_spec(self):
        schema = _amplifier_schema()
        result = collect(schema, answers={})
        assert isinstance(result, QuerySpec)

    def test_component_type_propagated(self):
        schema = _amplifier_schema()
        result = collect(schema, answers={})
        assert result.component_type == "amplifier"


class TestCollectEdgeCases:
    def test_min_equal_to_max_is_valid(self):
        """min == max is a degenerate range but should not raise."""
        schema = _amplifier_schema()
        answers = {
            "freq_range.min": "5",
            "freq_range.max": "5",
            "freq_range.unit": "GHz",
        }
        result = collect(schema, answers=answers)
        assert result.constraints[0].range == (5.0, 5.0)

    def test_float_string_answers_parsed(self):
        schema = _amplifier_schema()
        answers = {
            "freq_range.min": "2.5",
            "freq_range.max": "5.5",
            "freq_range.unit": "GHz",
        }
        result = collect(schema, answers=answers)
        assert result.constraints[0].range == (2.5, 5.5)

    def test_empty_string_value_skips_field(self):
        schema = _amplifier_schema()
        answers = {
            "P1dB.value": "",
            "P1dB.unit": "dBm",
        }
        result = collect(schema, answers=answers)
        names = [c.canonical_name for c in result.constraints]
        assert "P1dB" not in names
