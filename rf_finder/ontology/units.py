"""Pure unit-conversion functions: frequency (→ GHz) and power (→ dBm) (REQ-2.5).

Supported conversions
---------------------
Frequency canonical unit: GHz
    Hz, kHz, MHz, GHz → GHz

Power canonical unit: dBm
    W, mW, dBm → dBm   (dBm = 10 * log10(mW))
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

    raise ValueError(
        f"Unsupported canonical unit '{canonical}'; expected 'GHz' or 'dBm'"
    )
