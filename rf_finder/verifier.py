"""Normalization, comparison, and per-parameter verdicts (REQ-4)."""

from __future__ import annotations

from rf_finder.models import (
    Candidate,
    ParamConstraint,
    ParamVerdict,
    QuerySpec,
    RawValue,
    VerifiedCandidate,
)
from rf_finder.ontology.parameters import PARAMETERS
from rf_finder.ontology.units import to_canonical


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compare(constraint: ParamConstraint, raw: RawValue) -> str:
    """Return ``"PASS"`` or ``"FAIL"`` by normalising both sides to canonical unit.

    The canonical unit is taken from the ontology (the parameter's
    ``canonical_unit``), not from ``constraint.unit``.  Both the candidate's
    raw value (in ``raw.unit``) and the requirement (in the user-chosen
    ``constraint.unit``) are converted into that canonical unit before
    comparison, so the user may pick any accepted unit (e.g. MHz, W).
    """
    canonical = PARAMETERS[constraint.canonical_name].canonical_unit

    if constraint.comparison == "contains":
        # Both candidate and required are (low, high) tuples.
        cand_low_raw, cand_high_raw = raw.value  # type: ignore[misc]
        req_low, req_high = constraint.range  # type: ignore[misc]

        cand_low = to_canonical(cand_low_raw, raw.unit, canonical)
        cand_high = to_canonical(cand_high_raw, raw.unit, canonical)
        req_low_c = to_canonical(req_low, constraint.unit, canonical)
        req_high_c = to_canonical(req_high, constraint.unit, canonical)

        if cand_low <= req_low_c and cand_high >= req_high_c:
            return "PASS"
        return "FAIL"

    # Scalar comparisons (min / max / eq)
    found = to_canonical(raw.value, raw.unit, canonical)  # type: ignore[arg-type]
    required = to_canonical(constraint.value, constraint.unit, canonical)

    if constraint.comparison == "min":
        return "PASS" if found >= required else "FAIL"
    if constraint.comparison == "max":
        return "PASS" if found <= required else "FAIL"
    if constraint.comparison == "eq":
        return "PASS" if found == required else "FAIL"

    raise ValueError(f"Unknown comparison rule: {constraint.comparison!r}")


def _decide(verdicts: list[ParamVerdict]) -> str:
    """Aggregate per-param verdicts into an overall outcome.

    Rules (design.md §7):
    - any FAIL   → ``"fail"``
    - any UNKNOWN → ``"partial"``
    - all PASS   → ``"match"``
    """
    statuses = {v.status for v in verdicts}
    if "FAIL" in statuses:
        return "fail"
    if "UNKNOWN" in statuses:
        return "partial"
    return "match"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify(spec: QuerySpec, candidate: Candidate) -> VerifiedCandidate:
    """Verify *candidate* against every constraint in *spec*.

    Returns a :class:`VerifiedCandidate` with per-param verdicts, an overall
    outcome, and a confidence label derived from ``candidate.source``.
    """
    verdicts: list[ParamVerdict] = []

    for constraint in spec.constraints:
        raw = candidate.raw_params.get(constraint.canonical_name)
        if raw is None:
            verdicts.append(
                ParamVerdict(
                    canonical_name=constraint.canonical_name,
                    status="UNKNOWN",
                    required=constraint,
                    found=None,
                )
            )
            continue

        status = _compare(constraint, raw)
        verdicts.append(
            ParamVerdict(
                canonical_name=constraint.canonical_name,
                status=status,
                required=constraint,
                found=raw,
            )
        )

    overall = _decide(verdicts)

    # Confidence: pass source through; anything unexpected → "unknown"
    confidence: str = candidate.source if candidate.source in ("table", "datasheet") else "unknown"

    return VerifiedCandidate(
        candidate=candidate,
        verdicts=verdicts,
        overall=overall,
        confidence=confidence,
    )
