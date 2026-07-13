## MODIFIED Requirements

### Requirement: Model field and enumeration contract

The shared models SHALL expose the following fields, and the cross-module string values SHALL be drawn from the enumerations below.

Fields:
- `ParamConstraint`: `canonical_name`, `comparison`, `value`, `range`, `unit`
- `QuerySpec`: `component_type`, `constraints` (a list of `ParamConstraint`)
- `RawValue`: `value` (a scalar or a `(low, high)` tuple), `unit`
- `Candidate`: `model`, `manufacturer`, `url`, `raw_params` (canonical-name → `RawValue`), `source`, `datasheet_url` (a per-part datasheet PDF link or `None`)
- `ParamVerdict`: `canonical_name`, `status`, `required` (the originating `ParamConstraint`), `found` (a `RawValue` or `None`)
- `VerifiedCandidate`: `candidate`, `verdicts`, `overall`, `confidence`

The `Candidate.datasheet_url` field SHALL default to `None` so existing adapters that do not set it construct unchanged; it is the datasheet enrichment stage's input for fetching the part's datasheet.

Enumerations:
- `comparison`: `min`, `max`, `contains`, `eq`, `between`
- verdict `status`: `PASS`, `FAIL`, `UNKNOWN`
- `overall`: `match`, `partial`, `fail`
- `source`: `table`, `datasheet`
- `confidence`: `table`, `datasheet`, `unknown`

#### Scenario: Candidate exposes its fields

- **WHEN** a `Candidate` is constructed
- **THEN** it exposes `model`, `manufacturer`, `url`, `raw_params`, `source`, and `datasheet_url`
- **AND** `raw_params` maps canonical parameter names to `RawValue` instances

#### Scenario: datasheet_url defaults to None

- **WHEN** a `Candidate` is constructed without a `datasheet_url`
- **THEN** its `datasheet_url` is `None`

#### Scenario: Verdict and verified-candidate values come from the enumerations

- **WHEN** a `ParamVerdict` is produced
- **THEN** its `status` is one of `PASS`, `FAIL`, `UNKNOWN`
- **AND** the enclosing `VerifiedCandidate.overall` is one of `match`, `partial`, `fail`
- **AND** its `confidence` is one of `table`, `datasheet`, `unknown`
