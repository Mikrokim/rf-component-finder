"""Tests for rf_finder/ontology/parameters.py and components.py — T4 Ontology (REQ-2.1–2.4, REQ-1.2, REQ-1.3)."""

import pytest

from rf_finder.ontology.parameters import PARAMETERS, ParamDef, params_for
from rf_finder.ontology.components import COMPONENTS, component_labels


_AMPLIFIER_PARAMS = {
    "freq_range", "P1dB", "Gain", "NF", "IP3", "Psat",
    "VDD", "Size", "MSL", "Temperature",
}


# ---------------------------------------------------------------------------
# params_for()
# ---------------------------------------------------------------------------

class TestParamsFor:
    def test_amplifier_returns_expected_params(self):
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

    def test_p1db_comparison_is_min(self):
        assert PARAMETERS["P1dB"].comparison == "min"

    def test_gain_comparison_is_min(self):
        assert PARAMETERS["Gain"].comparison == "min"

    def test_nf_comparison_is_max(self):
        assert PARAMETERS["NF"].comparison == "max"

    def test_ip3_comparison_is_min(self):
        assert PARAMETERS["IP3"].comparison == "min"

    def test_psat_comparison_is_min(self):
        assert PARAMETERS["Psat"].comparison == "min"


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

    def test_ip3_canonical_unit_is_dbm(self):
        assert PARAMETERS["IP3"].canonical_unit == "dBm"

    def test_psat_canonical_unit_is_dbm(self):
        assert PARAMETERS["Psat"].canonical_unit == "dBm"


# ---------------------------------------------------------------------------
# freq_range units list
# ---------------------------------------------------------------------------

class TestFreqRangeUnits:
    def test_freq_range_units_list(self):
        # Derived from the converters: every frequency unit, canonical first.
        assert PARAMETERS["freq_range"].units == ["GHz", "MHz", "kHz", "Hz"]

    def test_freq_range_canonical_is_first_unit(self):
        units = PARAMETERS["freq_range"].units
        assert units[0] == PARAMETERS["freq_range"].canonical_unit

    def test_power_params_offer_every_convertible_unit(self):
        # Every dBm parameter (incl. IP3) offers the full power unit set.
        for name in ("P1dB", "Psat", "IP3"):
            assert PARAMETERS[name].units == ["dBm", "W", "mW"]

    def test_params_without_a_converter_offer_only_their_canonical(self):
        for name in ("Gain", "NF", "VDD", "Size", "Temperature", "MSL"):
            p = PARAMETERS[name]
            assert p.units == [p.canonical_unit]

    def test_every_offered_unit_is_convertible(self):
        # The invariant that makes deriving units safe: every unit the form
        # offers must actually convert to that parameter's canonical unit, so a
        # user can never pick a unit the verifier then chokes on.
        from rf_finder.ontology.units import to_canonical

        for name, p in PARAMETERS.items():
            for unit in p.units:
                # value=2.0 (positive) so power conversions don't reject it.
                to_canonical(2.0, unit, p.canonical_unit)   # must not raise


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
