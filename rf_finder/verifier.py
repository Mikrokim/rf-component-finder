"""Normalization, comparison, and per-parameter verdicts (REQ-4)."""

from __future__ import annotations

import math

from rf_finder.models import (
    Candidate,
    ParamConstraint,
    ParamVerdict,
    QuerySpec,
    RawValue,
    VerifiedCandidate,
)
from rf_finder.ontology.units import to_canonical


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compare(constraint: ParamConstraint, raw: RawValue) -> str:
    """Return ``"PASS"`` or ``"FAIL"`` by normalising both sides to canonical unit.

    The canonical unit is taken from ``constraint.unit`` — callers must ensure
    the constraint's unit is a valid canonical target for ``to_canonical``.
    """
    canonical = constraint.unit

    if constraint.comparison == "contains":
        # Both candidate and required are (low, high) tuples.
        cand_low_raw, cand_high_raw = raw.value  # type: ignore[misc]
        req_low, req_high = constraint.range  # type: ignore[misc]

        cand_low = to_canonical(cand_low_raw, raw.unit, canonical)
        cand_high = to_canonical(cand_high_raw, raw.unit, canonical)
        req_low_c = to_canonical(req_low, canonical, canonical)   # identity
        req_high_c = to_canonical(req_high, canonical, canonical)

        if cand_low <= req_low_c and cand_high >= req_high_c:
            return "PASS"
        return "FAIL"

    # Scalar comparisons (min / max / eq)
    found = to_canonical(raw.value, raw.unit, canonical)  # type: ignore[arg-type]
    required = to_canonical(constraint.value, canonical, canonical)  # identity

    if constraint.comparison == "min":
        return "PASS" if found >= required else "FAIL"
    if constraint.comparison == "max":
        return "PASS" if found <= required else "FAIL"
    if constraint.comparison == "eq":
        return "PASS" if math.isclose(found, required, rel_tol=1e-9, abs_tol=1e-9) else "FAIL"

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
