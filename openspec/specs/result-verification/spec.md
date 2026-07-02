# Result Verification Specification

## Purpose

Define how a retrieved candidate is checked against the user's `QuerySpec`: each constraint is normalized to its canonical unit and compared, producing a per-parameter verdict, an overall outcome, and a confidence label. This spec documents the behavior **as currently implemented** in `rf_finder/verifier.py`, including a current limitation in `eq`/unknown-parameter handling.

## Requirements

### Requirement: Verify a candidate against a query spec

The system SHALL provide `verify(spec, candidate) -> VerifiedCandidate` producing one `ParamVerdict` per constraint, an overall outcome, and a confidence label. For each constraint, IF the parameter is absent from the candidate's `raw_params`, the verdict status SHALL be `UNKNOWN` with `found = None`; otherwise the candidate's raw value SHALL be compared and carried on the verdict. The returned `VerifiedCandidate` SHALL reference the original candidate, and each verdict SHALL reference the original constraint.

#### Scenario: Missing parameter yields UNKNOWN

- **WHEN** a constraint's parameter is not present in the candidate's `raw_params`
- **THEN** the verdict status is `UNKNOWN` and its `found` is `None`

#### Scenario: Verdict carries the originating constraint and raw value

- **WHEN** a constraint's parameter is present and compared
- **THEN** the verdict's `required` is the original `ParamConstraint`
- **AND** the verdict's `found` is the candidate's `RawValue`
- **AND** `verify` returns a `VerifiedCandidate` whose `candidate` is the input candidate

### Requirement: Range containment comparison (contains)

For a `contains` constraint, the candidate's `(low, high)` band and the required `(low, high)` band SHALL both be normalized to the parameter's canonical unit (taken from the ontology, not from the constraint unit). The verdict SHALL be `PASS` when `cand_low <= req_low` and `cand_high >= req_high`, otherwise `FAIL`. The user MAY express the required band in any accepted unit (e.g. MHz against a GHz canonical).

#### Scenario: Candidate band fully covers the required band

- **WHEN** the candidate band `(1.0, 8.0) GHz` is checked against required `(2.0, 6.0) GHz`
- **THEN** the verdict is `PASS`

#### Scenario: Candidate band misses an end

- **WHEN** the candidate band `(3.0, 8.0) GHz` is checked against required `(2.0, 6.0) GHz`
- **THEN** the verdict is `FAIL` (low end not covered)

#### Scenario: Units are normalized on both sides

- **WHEN** the candidate band `(2000.0, 6000.0) MHz` is checked against required `(2.0, 6.0) GHz`
- **THEN** the verdict is `PASS`
- **AND WHEN** the required band is `(2000.0, 6000.0) MHz` against a candidate `(1.0, 8.0) GHz`, the verdict is `PASS`

### Requirement: Scalar threshold comparisons (min, max)

For a `min` constraint the verdict SHALL be `PASS` when the normalized found value is `>=` the normalized required value; for a `max` constraint, `PASS` when `<=`. Both the candidate value and the required value SHALL be normalized to the parameter's canonical unit, so the user MAY supply the requirement in any accepted unit (e.g. watts against a dBm canonical). Boundary equality SHALL be `PASS`.

#### Scenario: Minimum threshold

- **WHEN** a `min` requirement of `26 dBm` is checked against a candidate `30 dBm`
- **THEN** the verdict is `PASS`
- **AND WHEN** the candidate is exactly `26 dBm`, the verdict is `PASS`
- **AND WHEN** the candidate is `20 dBm`, the verdict is `FAIL`

#### Scenario: Requirement in a non-canonical unit is normalized

- **WHEN** a `min` requirement of `0.1 W` (= 20 dBm) is checked against a candidate `25 dBm`
- **THEN** the verdict is `PASS`

### Requirement: Overall outcome aggregation

The system SHALL aggregate per-parameter verdicts into an overall outcome: IF any verdict is `FAIL` the outcome SHALL be `fail`; ELSE IF any verdict is `UNKNOWN` the outcome SHALL be `partial`; ELSE (all `PASS`) the outcome SHALL be `match`.

#### Scenario: Fail dominates

- **WHEN** the verdicts contain at least one `FAIL` alongside `PASS` or `UNKNOWN`
- **THEN** the overall outcome is `fail`

#### Scenario: Unknown without fail is partial

- **WHEN** the verdicts contain an `UNKNOWN` and no `FAIL`
- **THEN** the overall outcome is `partial`

#### Scenario: All pass is a match

- **WHEN** every verdict is `PASS`
- **THEN** the overall outcome is `match`

### Requirement: Confidence derived from candidate source

The system SHALL set `VerifiedCandidate.confidence` from `candidate.source`: `table` and `datasheet` SHALL pass through unchanged; any other value SHALL map to `unknown`.

#### Scenario: Source maps to confidence

- **WHEN** the candidate's `source` is `table`
- **THEN** the confidence is `table`
- **AND WHEN** the source is `datasheet`, the confidence is `datasheet`
- **AND WHEN** the source is any unrecognized string, the confidence is `unknown`

### Requirement: Between comparison (band membership)

For a `between` constraint the candidate carries a single scalar value and the requirement is a `(low, high)` band. The found value and both bounds SHALL be normalized to the parameter's canonical unit, and the verdict SHALL be `PASS` when `low <= value <= high`, otherwise `FAIL`. Either bound MAY be open (`-inf` / `+inf`), giving a one-sided range. Of the current amplifier parameters only `VDD` uses `between`.

#### Scenario: Value inside the band passes

- **WHEN** a `between` requirement of `(20.0, 30.0)` is checked against a candidate value of `26`
- **THEN** the verdict is `PASS`
- **AND WHEN** the candidate value is `18`, the verdict is `FAIL`

#### Scenario: One-sided band imposes a single bound

- **WHEN** a `between` requirement of `(26.0, +inf)` is checked
- **THEN** a candidate value of `30` is `PASS`
- **AND WHEN** the candidate value is `20`, the verdict is `FAIL`

### Requirement: Equality and unknown-parameter handling (current behavior)

The comparator SHALL look up a constraint's canonical unit from the ontology by its `canonical_name`. Verifying a present candidate value for a `canonical_name` that is not defined in the ontology SHALL raise `KeyError`. The `eq` rule is implemented as a tolerant float comparison, but no ontology parameter currently uses `eq`, so it is not exercised in normal operation.

#### Scenario: Unknown parameter name raises KeyError

- **WHEN** `verify` compares a present value for a constraint whose `canonical_name` is not in the ontology (e.g. an `eq` constraint on `freq_point`)
- **THEN** a `KeyError` is raised
