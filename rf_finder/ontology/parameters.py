"""Central parameter dictionary: labels, canonical units, comparison rules, applies_to (REQ-2.1–2.4)."""

from __future__ import annotations

from typing import NamedTuple


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
    """

    label: str
    canonical_unit: str
    units: list[str]
    comparison: str
    applies_to: list[str]


PARAMETERS: dict[str, ParamDef] = {
    "freq_range": ParamDef(
        label="Frequency range",
        canonical_unit="GHz",
        units=["GHz", "MHz"],
        comparison="contains",
        applies_to=["amplifier", "mixer", "filter", "attenuator"],
    ),
    "P1dB": ParamDef(
        label="P1dB (output 1 dB compression)",
        canonical_unit="dBm",
        units=["dBm", "W", "mW"],
        comparison="min",
        applies_to=["amplifier"],
    ),
    "Gain": ParamDef(
        label="Gain",
        canonical_unit="dB",
        units=["dB"],
        comparison="min",
        applies_to=["amplifier"],
    ),
    "NF": ParamDef(
        label="Noise figure",
        canonical_unit="dB",
        units=["dB"],
        comparison="max",
        applies_to=["amplifier"],
    ),
    "IP3": ParamDef(
        label="IP3",
        canonical_unit="dBm",
        units=["dBm"],
        comparison="min",
        applies_to=["amplifier"],
    ),
    "Psat": ParamDef(
        label="Saturated power (Psat)",
        canonical_unit="dBm",
        units=["dBm", "W", "mW"],
        comparison="min",
        applies_to=["amplifier"],
    ),
    "VDD": ParamDef(
        label="Supply voltage (VDD)",
        canonical_unit="V",
        units=["V"],
        comparison="contains",
        applies_to=["amplifier"],
    ),
    "Size": ParamDef(
        label="Size",
        canonical_unit="mm",
        units=["mm"],
        comparison="max",
        applies_to=["amplifier"],
    ),
    "MSL": ParamDef(
        label="MSL level (1–5)",
        canonical_unit="",
        units=[""],
        comparison="max",
        applies_to=["amplifier"],
    ),
    "Temperature": ParamDef(
        label="Operating temperature",
        canonical_unit="degC",
        units=["degC"],
        comparison="contains",
        applies_to=["amplifier"],
    ),
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
