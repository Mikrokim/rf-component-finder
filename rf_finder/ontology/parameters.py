"""Central parameter dictionary: labels, canonical units, comparison rules, applies_to (REQ-2.1–2.4)."""

from __future__ import annotations

from typing import NamedTuple

from rf_finder.ontology.units import units_for


class ParamDef(NamedTuple):
    """Immutable definition of one measurable parameter.

    Fields
    ------
    label:          Human-readable name shown in the form.
    canonical_unit: The unit everything is normalised to (e.g. "GHz", "dBm", "dB").
    units:          Accepted unit strings offered in the form's unit selector
                    (canonical unit listed first, per REQ-1.4).
    comparison:     Rule used by the Verifier: "min" | "max" | "contains" | "eq" | "between".
    applies_to:     Component types for which this parameter is relevant.
    single_value_ok:
                    For a ``contains`` field, whether the form accepts a SINGLE
                    value (one entry → the point ``(v, v)``) in addition to a full
                    range. VDD supports this ("must operate at exactly this
                    voltage"); freq_range / Temperature are always bands and
                    require both bounds. Ignored for non-``contains`` rules.
    """

    label: str
    canonical_unit: str
    units: list[str]
    comparison: str
    applies_to: list[str]
    single_value_ok: bool = False


def _param(
    label: str,
    canonical_unit: str,
    comparison: str,
    applies_to: list[str],
    *,
    single_value_ok: bool = False,
) -> ParamDef:
    """Build a ``ParamDef`` whose accepted ``units`` are *derived* from its
    canonical unit via ``units_for`` — so the form always offers exactly the
    units the converters support, with no hand-maintained list to drift.
    """
    return ParamDef(
        label=label,
        canonical_unit=canonical_unit,
        units=units_for(canonical_unit),
        comparison=comparison,
        applies_to=applies_to,
        single_value_ok=single_value_ok,
    )


PARAMETERS: dict[str, ParamDef] = {
    "freq_range": _param(
        "Frequency range", "GHz", "contains",
        ["amplifier", "mixer", "filter", "attenuator"],
    ),
    "P1dB": _param("P1dB (output 1 dB compression)", "dBm", "min", ["amplifier"]),
    "Gain": _param("Gain", "dB", "min", ["amplifier"]),
    "NF": _param("Noise figure", "dB", "max", ["amplifier"]),
    "IP3": _param("IP3", "dBm", "min", ["amplifier"]),
    "Psat": _param("Saturated power (Psat)", "dBm", "min", ["amplifier"]),
    "VDD": _param("Supply voltage (VDD)", "V", "contains", ["amplifier"], single_value_ok=True),
    "Size": _param("Size", "mm", "max", ["amplifier"]),
    "MSL": _param("MSL level (1–5)", "", "max", ["amplifier"]),
    "Temperature": _param("Operating temperature", "degC", "contains", ["amplifier"]),
}


def params_for(component_type: str) -> dict[str, ParamDef]:
    """Return all parameters that apply to *component_type*.

    Parameters
    ----------
    component_type: canonical component name (e.g. ``"amplifier"``).

    Returns
    -------
    dict keyed by parameter name; empty dict if *component_type* is unknown.
    """
    return {
        name: param
        for name, param in PARAMETERS.items()
        if component_type in param.applies_to
    }
