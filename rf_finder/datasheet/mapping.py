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
  - ``contains`` (freq_range, Temperature) and ``overlap`` (VDD): a continuous
    ``(low, high)`` range, or a list of discrete options — the band-valued
    candidate shapes both rules compare in ``verifier._compare``.
  - ``min`` / ``max`` / ``eq`` (Gain, NF, P1dB, Size, MSL, ...): a single scalar,
    picked as the candidate's GUARANTEED value by comparison direction — the
    stated ``min`` (falling back to ``typ``) for a ``min`` rule ("at least"), the
    stated ``max`` (falling back to ``typ``) for a ``max`` rule ("at most"), the
    ``typ`` for ``eq``.  The fallback never borrows the OPPOSITE end (``max`` for
    a ``min`` rule, or ``min`` for a ``max`` rule), which would be optimistic; a
    parameter with neither the matching field nor ``typ`` is left UNKNOWN.

Parameters the ontology does not define, not-found params (``None``), and specs
whose unit is missing on a multi-unit parameter (ambiguous) are skipped so the
Verifier reports them as ``UNKNOWN`` rather than mis-comparing or guessing.
Multi-option params (``value`` is a list, e.g. a supply with several selectable
voltages) map to a list ``RawValue``, which ``contains``/``overlap`` support —
they are verified like any other parameter.
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


def _normalize_unit(unit, pdef) -> str | None:
    """Reconcile the emitted unit with the ontology's canonical spelling.

    A STATED unit is alias-reconciled (e.g. ``"C"`` -> ``"degC"``) or passed
    through unchanged.  A MISSING/empty unit is filled from the ontology ONLY
    when the parameter is unambiguous — it has a single accepted unit
    (``len(pdef.units) == 1``), which covers dimensionless params (MSL, canonical
    ``""``) and single-unit ones (Gain -> ``"dB"``).  For a MULTI-unit parameter
    (``freq_range`` GHz/MHz, ``P1dB``/``Psat`` dBm/W/mW) a missing unit is
    genuinely ambiguous, so this returns ``None`` rather than guess the canonical
    unit — the caller then omits the parameter and the Verifier reports it
    UNKNOWN, consistent with the "never guess an optimistic value" rule the
    min/max scalar picks use above.
    """
    if unit is not None and unit != "":
        return _UNIT_ALIASES.get(unit, unit)
    if len(pdef.units) == 1:
        return pdef.canonical_unit
    return None


def _to_value(spec: dict, comparison: str):
    """Return the ``RawValue.value`` for *spec* under *comparison*, or None."""
    val = spec.get("value")

    if comparison in ("contains", "overlap"):
        # Band-valued candidate: discrete, selectable options (e.g. VDD 3/5/8 V)
        # -> list.
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
        # For overlap (VDD) a single stated supply figure is a degenerate
        # (v, v) interval — the shape a single-value site cell also yields.
        # ``contains`` params (freq_range/Temperature) keep their range-only
        # behaviour: a lone figure there stays UNKNOWN.
        if comparison == "overlap":
            single = spec.get("typ")
            if single is None and len(nums) == 1:
                single = nums[0]
            if single is not None:
                return (float(single), float(single))
        return None

    # Scalar comparisons: pick the guaranteed figure by comparison direction.
    # The fallback stops at ``typ`` and never borrows the OPPOSITE end: for a
    # "min" ("at least") rule, using a stated ``max`` as the guaranteed floor
    # would be badly optimistic, so ``max`` is not a fallback here (and vice
    # versa for "max"). When neither the ideal field nor ``typ`` is stated, the
    # parameter is left unresolved -> UNKNOWN rather than guessed.
    if comparison == "min":
        for cand in (spec.get("min"), spec.get("typ")):
            if cand is not None:
                return float(cand)
        nums = _numbers(val)
        return min(nums) if nums else None

    if comparison == "max":
        for cand in (spec.get("max"), spec.get("typ")):
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
    (``None``), specs from which no value can be formed, and specs whose unit is
    missing on a MULTI-unit parameter (ambiguous — see ``_normalize_unit``) are
    omitted — the Verifier then reports those constraints as ``UNKNOWN``.
    """
    raw: dict[str, RawValue] = {}
    for name, spec in params.items():
        pdef = PARAMETERS.get(name)
        if pdef is None or not isinstance(spec, dict):
            continue
        value = _to_value(spec, pdef.comparison)
        if value is None:
            continue
        unit = _normalize_unit(spec.get("unit"), pdef)
        if unit is None:
            # Ambiguous: a multi-unit parameter arrived without a unit — don't
            # guess the canonical unit; leave it UNKNOWN.
            continue
        raw[name] = RawValue(value=value, unit=unit)
    return raw
