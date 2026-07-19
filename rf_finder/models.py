"""Frozen dataclasses: QuerySpec, ParamConstraint, Candidate, ParamVerdict, VerifiedCandidate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# String-constant groups (§5 of data-models.md)
# ---------------------------------------------------------------------------

Comparison = Literal["min", "max", "contains", "overlap", "eq", "between"]
VerdictStatus = Literal["PASS", "FAIL", "UNKNOWN"]
Overall = Literal["match", "partial", "fail"]
Source = Literal["table", "datasheet"]
Confidence = Literal["table", "datasheet", "unknown"]


# ---------------------------------------------------------------------------
# 2. Input Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamConstraint:
    """A single requirement on one parameter (REQ-1.4, REQ-1.5, REQ-2.4).

    Invariant: exactly one of ``value`` / ``range`` is non-None.
    """

    canonical_name: str                   # e.g. "P1dB", "freq_range"
    comparison: str                       # "min" | "max" | "contains" | "overlap" | "eq" | "between"
    value: float | None                   # for min/max/eq, in the chosen unit
    range: tuple[float, float] | None     # for "contains"/"overlap"/"between" (e.g. (2.0, 6.0))
    unit: str                             # e.g. "dBm", "GHz"

    def __post_init__(self) -> None:
        both_none = self.value is None and self.range is None
        both_set = self.value is not None and self.range is not None
        if both_none or both_set:
            raise ValueError(
                "ParamConstraint: exactly one of 'value' or 'range' must be non-None "
                f"(got value={self.value!r}, range={self.range!r})"
            )


@dataclass(frozen=True)
class QuerySpec:
    """Structured search built from the form (REQ-1.1, REQ-1.6, REQ-1.7)."""

    component_type: str                   # canonical, e.g. "amplifier"
    constraints: list[ParamConstraint]    # only the filled fields (REQ-1.6)


# ---------------------------------------------------------------------------
# 3. Retrieval Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RawValue:
    """A value exactly as found on a manufacturer source, before unit normalization."""

    value: float | tuple[float, float] | list[float]
    # scalar; a (low, high) continuous range; or a list of discrete options
    # (e.g. a VDD supporting 3, 5 or 8 V exactly — NOT the whole 3–8 V continuum).
    unit: str                            # source unit, pre-normalization (e.g. "MHz")


@dataclass(frozen=True)
class Candidate:
    """One component returned by an Adapter, not yet verified (REQ-3.5)."""

    model: str
    manufacturer: str
    url: str
    raw_params: dict[str, RawValue]      # canonical_name -> RawValue
    source: str                          # "table" | "datasheet"


# ---------------------------------------------------------------------------
# 4. Verification Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamVerdict:
    """Result of checking one constraint against one candidate (REQ-4.1, REQ-4.2)."""

    canonical_name: str
    status: str                          # "PASS" | "FAIL" | "UNKNOWN"
    required: ParamConstraint            # what was asked
    found: RawValue | None               # what the candidate had (None => UNKNOWN)


@dataclass(frozen=True)
class VerifiedCandidate:
    """A candidate plus its full verdict set and overall outcome (REQ-4.3–4.5)."""

    candidate: Candidate
    verdicts: list[ParamVerdict]
    overall: str                         # "match" | "partial" | "fail"
    confidence: str                      # "table" | "datasheet" | "unknown"
