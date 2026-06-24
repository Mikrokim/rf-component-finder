"""Tests for rf_finder/ontology/parameters.py and components.py — T4 Ontology (REQ-2.1–2.4, REQ-1.2, REQ-1.3)."""

import pytest

from rf_finder.ontology.parameters import PARAMETERS, ParamDef, params_for
from rf_finder.ontology.components import COMPONENTS, component_labels


_AMPLIFIER_PARAMS = {"freq_range", "P1dB", "Gain", "NF", "OIP3", "Pout"}


# ---------------------------------------------------------------------------
# params_for()
# ---------------------------------------------------------------------------

class TestParamsFor:
    def test_amplifier_returns_exactly_six_params(self):
        result = params_for("amplifier")
        assert set(result.keys()) == _AMPLIFIER_PARAMS

    def test_unknown_component_returns_empty_dict(self):
        assert params_for("unknown") == {}

    def test_unknown_component_empty_not_none(self):
        result = params_for("thereallyunknowntype")
        assert result is not None
        assert len(result) == 0

    def test_returns_paramdef_values(self):
        result = params_for("amplifier")
        for value in result.values():
            assert isinstance(value, ParamDef)


# ---------------------------------------------------------------------------
# comparison values for each of the 6 amplifier params
# ---------------------------------------------------------------------------

class TestComparisons:
    def test_freq_range_comparison_is_contains(self):
        assert PARAMETERS["freq_range"].comparison == "contains"

    def test_p1db_comparison_is_between(self):
        assert PARAMETERS["P1dB"].comparison == "between"

    def test_gain_comparison_is_between(self):
        assert PARAMETERS["Gain"].comparison == "between"

    def test_nf_comparison_is_max(self):
        assert PARAMETERS["NF"].comparison == "max"

    def test_oip3_comparison_is_between(self):
        assert PARAMETERS["OIP3"].comparison == "between"

    def test_pout_comparison_is_min(self):
        assert PARAMETERS["Pout"].comparison == "min"


# ---------------------------------------------------------------------------
# canonical_unit values for each of the 6 amplifier params
# ---------------------------------------------------------------------------

class TestCanonicalUnits:
    def test_freq_range_canonical_unit_is_ghz(self):
        assert PARAMETERS["freq_range"].canonical_unit == "GHz"

    def test_p1db_canonical_unit_is_dbm(self):
        assert PARAMETERS["P1dB"].canonical_unit == "dBm"

    def test_gain_canonical_unit_is_db(self):
        assert PARAMETERS["Gain"].canonical_unit == "dB"

    def test_nf_canonical_unit_is_db(self):
        assert PARAMETERS["NF"].canonical_unit == "dB"

    def test_oip3_canonical_unit_is_dbm(self):
        assert PARAMETERS["OIP3"].canonical_unit == "dBm"

    def test_pout_canonical_unit_is_dbm(self):
        assert PARAMETERS["Pout"].canonical_unit == "dBm"


# ---------------------------------------------------------------------------
# freq_range units list
# ---------------------------------------------------------------------------

class TestFreqRangeUnits:
    def test_freq_range_units_list(self):
        assert PARAMETERS["freq_range"].units == ["GHz", "MHz"]

    def test_freq_range_canonical_is_first_unit(self):
        units = PARAMETERS["freq_range"].units
        assert units[0] == PARAMETERS["freq_range"].canonical_unit


# ---------------------------------------------------------------------------
# component_labels() and COMPONENTS
# ---------------------------------------------------------------------------

class TestComponents:
    def test_component_labels_returns_amplifier_mapping(self):
        assert component_labels() == {"amplifier": "Amplifier"}

    def test_components_amplifier_label(self):
        assert COMPONENTS["amplifier"]["label"] == "Amplifier"

    def test_component_labels_is_dict(self):
        labels = component_labels()
        assert isinstance(labels, dict)


# ---------------------------------------------------------------------------
# applies_to: all 6 params include "amplifier"
# ---------------------------------------------------------------------------

class TestAppliesTo:
    @pytest.mark.parametrize("param_name", list(_AMPLIFIER_PARAMS))
    def test_amplifier_in_applies_to(self, param_name):
        assert "amplifier" in PARAMETERS[param_name].applies_to


# ---------------------------------------------------------------------------
# ParamDef immutability
# ---------------------------------------------------------------------------

class TestParamDefImmutability:
    def test_paramdef_is_named_tuple(self):
        # NamedTuple instances are tuples and therefore immutable
        p = PARAMETERS["Gain"]
        assert isinstance(p, tuple)

    def test_paramdef_cannot_be_mutated(self):
        p = PARAMETERS["Gain"]
        with pytest.raises((AttributeError, TypeError)):
            p.label = "modified"  # type: ignore[misc]
