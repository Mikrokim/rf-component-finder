"""Pure unit-conversion functions: frequency (→ GHz), power (→ dBm), and
dimensionless ratios (→ dB) (REQ-2.5).

Supported conversions
---------------------
Frequency canonical unit: GHz
    Hz, kHz, MHz, GHz → GHz

Power canonical unit: dBm
    W, mW, dBm → dBm   (dBm = 10 * log10(mW))

Ratio canonical unit: dB
    dB → dB            (identity; dB is a dimensionless ratio, e.g. gain, NF)
"""

import math

# ---------------------------------------------------------------------------
# Frequency: all → GHz
# ---------------------------------------------------------------------------

_FREQ_TO_GHZ: dict[str, float] = {
    "Hz":  1e-9,
    "kHz": 1e-6,
    "MHz": 1e-3,
    "GHz": 1.0,
}

# ---------------------------------------------------------------------------
# Power: all → dBm
# ---------------------------------------------------------------------------

def _power_to_dbm(value: float, from_unit: str) -> float:
    if from_unit == "dBm":
        return value
    if from_unit == "mW":
        if value <= 0:
            raise ValueError(f"Cannot convert non-positive power {value} mW to dBm")
        return 10.0 * math.log10(value)
    if from_unit == "W":
        mw = value * 1000.0
        if mw <= 0:
            raise ValueError(f"Cannot convert non-positive power {value} W to dBm")
        return 10.0 * math.log10(mw)
    raise ValueError(f"Unknown power unit '{from_unit}'; expected one of: W, mW, dBm")


# ---------------------------------------------------------------------------
# Which units may be entered for each canonical unit (drives the form selectors)
# ---------------------------------------------------------------------------

#: Every source unit convertible to a given canonical unit, canonical first.
#: This is the single source of truth for the unit selectors: the ontology
#: derives each parameter's accepted units from it (see ``parameters.units_for``),
#: so a unit added to the converters here appears in the form automatically.
_CANONICAL_UNITS: dict[str, list[str]] = {
    # Frequency: derived from the conversion table, canonical (largest) first.
    "GHz": sorted(_FREQ_TO_GHZ, key=lambda u: -_FREQ_TO_GHZ[u]),
    # Power: dBm canonical, plus the linear units ``_power_to_dbm`` accepts.
    "dBm": ["dBm", "W", "mW"],
    # Ratio: dimensionless — only dB.
    "dB": ["dB"],
}


def units_for(canonical: str) -> list[str]:
    """Return all units convertible to *canonical*, canonical first.

    A canonical unit with no alternative-unit converter (e.g. ``V``, ``mm``,
    ``degC``, ``""``) returns ``[canonical]`` — its only accepted unit. A fresh
    list is returned each call so callers can't mutate the registry.
    """
    return list(_CANONICAL_UNITS.get(canonical, [canonical]))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def to_canonical(value: float, from_unit: str, canonical: str) -> float:
    """Convert *value* from *from_unit* to *canonical* unit.

    Parameters
    ----------
    value:     numeric value in *from_unit*.
    from_unit: source unit string (case-sensitive).
    canonical: target canonical unit — must be ``"GHz"`` or ``"dBm"``.

    Returns
    -------
    float — value expressed in *canonical* units.

    Raises
    ------
    ValueError — unknown unit, unsupported canonical, or non-positive power.
    """
    # Identity: a value already in the canonical unit needs no conversion.
    # Also covers dimensionless ratios like "dB" (Gain, NF), whose only unit
    # is the canonical one, and lets open bounds (0, +inf) pass through cleanly.
    if from_unit == canonical:
        return value

    if canonical == "GHz":
        factor = _FREQ_TO_GHZ.get(from_unit)
        if factor is None:
            raise ValueError(
                f"Unknown frequency unit '{from_unit}'; "
                f"expected one of: {', '.join(_FREQ_TO_GHZ)}"
            )
        return value * factor

    if canonical == "dBm":
        return _power_to_dbm(value, from_unit)

    if canonical == "dB":
        # dB is a dimensionless ratio (gain, noise figure, …); its only valid
        # source unit is dB itself, so the conversion is the identity.
        if from_unit != "dB":
            raise ValueError(
                f"Unknown ratio unit '{from_unit}'; expected 'dB'"
            )
        return value

    raise ValueError(
        f"Unsupported canonical unit '{canonical}'; expected 'GHz', 'dBm', or 'dB'"
    )
