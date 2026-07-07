"""Map extracted datasheet parameters onto the Verifier's ``RawValue`` model.

``extract_rf_parameters`` returns model-facing dicts
``{unit, min, typ, max, value, condition}``.  The Verifier
(``rf_finder.verifier``) consumes ``RawValue(value, unit)`` keyed by the
ontology's canonical parameter name.  This module bridges the two, in
accordance with:

  - ``ontology.parameters`` — the parameter's ``comparison`` rule decides the
    ``RawValue`` shape, and ``canonical_unit`` decides the fallback unit.
  - ``models.RawValue`` — ``value`` is a scalar, a ``(low, high)`` range, or a
    list of discrete options; ``unit`` is a source-unit string.
  - ``ontology.units`` — ``to_canonical`` only converts frequency/power/ratio
    or passes a matching unit through unchanged, so unit spellings the model
    emits (e.g. ``"C"``) are reconciled here to the canonical one (``"degC"``).

The shape is chosen from each parameter's ``comparison``:
  - ``contains`` (freq_range, VDD, Temperature): a continuous ``(low, high)``
    range, or a list of discrete options — matching the two ``contains``
    branches in ``verifier._compare``.
  - ``min`` / ``max`` / ``eq`` (Gain, NF, P1dB, Size, MSL, ...): a single scalar,
    picked as the candidate's GUARANTEED value — the smallest stated figure for
    ``min`` ("at least"), the largest for ``max`` ("at most"), the typical for
    ``eq``.

Parameters the ontology does not define, and not-found params (``None``), are
skipped so the Verifier reports them as ``UNKNOWN`` rather than mis-comparing.
Tunable multi-option params (``value`` is a list) map to a list ``RawValue``,
which ``contains`` supports; a caller that wants to defer them can run
``split_tunable`` first and map only the resolved bucket.
"""

from __future__ import annotations

import re

from rf_finder.models import RawValue
from rf_finder.ontology.parameters import PARAMETERS

# Unit spellings a datasheet / LLM may emit that differ from the ontology's
# canonical spelling.  Anything not listed passes through unchanged.
_UNIT_ALIASES = {
    "C": "degC",
    "°C": "degC",
    "degrees C": "degC",
    "Ohms": "Ohm",
}

_NUMBER = re.compile(r"[-+]?\d*\.?\d+")


def _numbers(value) -> list[float]:
    """Every number in *value*, whether it is a number, a list, or free text."""
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, list):
        out: list[float] = []
        for item in value:
            out.extend(_numbers(item))
        return out
    return [float(m) for m in _NUMBER.findall(str(value))]


def _normalize_unit(unit, canonical_unit: str) -> str:
    """Reconcile the emitted unit with the ontology's canonical spelling."""
    if unit is None or unit == "":
        return canonical_unit
    return _UNIT_ALIASES.get(unit, unit)


def _to_value(spec: dict, comparison: str):
    """Return the ``RawValue.value`` for *spec* under *comparison*, or None."""
    val = spec.get("value")

    if comparison == "contains":
        # Discrete, selectable options (e.g. VDD 3/5/8 V) -> list.
        if isinstance(val, list) and val:
            nums = _numbers(val)
            return nums or None
        # Continuous range -> (low, high).
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None and hi is not None:
            return (float(lo), float(hi))
        # Fall back to a two-ended range parsed from an "A to B" string.
        nums = _numbers(val)
        if len(nums) >= 2:
            return (min(nums), max(nums))
        return None

    # Scalar comparisons: pick the guaranteed figure by comparison direction.
    if comparison == "min":
        for cand in (spec.get("min"), spec.get("typ"), spec.get("max")):
            if cand is not None:
                return float(cand)
        nums = _numbers(val)
        return min(nums) if nums else None

    if comparison == "max":
        for cand in (spec.get("max"), spec.get("typ"), spec.get("min")):
            if cand is not None:
                return float(cand)
        nums = _numbers(val)
        return max(nums) if nums else None

    # eq (and any other single-value rule): the typical value.
    for cand in (spec.get("typ"), spec.get("min"), spec.get("max")):
        if cand is not None:
            return float(cand)
    nums = _numbers(val)
    return nums[0] if nums else None


def to_raw_params(params: dict) -> dict[str, RawValue]:
    """Convert extractor output into ``{canonical_name: RawValue}`` for the Verifier.

    *params* is keyed by ontology canonical names (e.g. ``"Gain"``,
    ``"Temperature"``).  Keys the ontology does not define, not-found params
    (``None``), and specs from which no value can be formed are omitted — the
    Verifier then reports those constraints as ``UNKNOWN``.
    """
    raw: dict[str, RawValue] = {}
    for name, spec in params.items():
        pdef = PARAMETERS.get(name)
        if pdef is None or not isinstance(spec, dict):
            continue
        value = _to_value(spec, pdef.comparison)
        if value is None:
            continue
        raw[name] = RawValue(
            value=value,
            unit=_normalize_unit(spec.get("unit"), pdef.canonical_unit),
        )
    return raw
