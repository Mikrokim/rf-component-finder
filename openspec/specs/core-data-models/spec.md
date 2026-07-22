# Core Data Models Specification

## Purpose

Define the shared, immutable data structures that flow through the pipeline and are produced/consumed across the form, adapter, and verifier layers. These models carry no behavior — comparison and normalization live in the Verifier and Units modules — which keeps them trivially serializable and unit-testable. This spec documents the structures **as currently implemented** in `rf_finder/models.py`. (The form-internal `Field`/`FormSchema` types are covered by `structured-form-input`; the `ParamDef` ontology type by `parameter-ontology`.)

## Requirements

### Requirement: Shared pipeline models are immutable

The six shared models — `ParamConstraint`, `QuerySpec`, `RawValue`, `Candidate`, `ParamVerdict`, and `VerifiedCandidate` — SHALL be immutable (`@dataclass(frozen=True)`). Attempting to reassign a field on any instance SHALL raise an error.

#### Scenario: Reassigning a field on a model is rejected

- **WHEN** code attempts to assign a new value to a field of any shared model (e.g. `param_constraint.value = 9.0`)
- **THEN** a `FrozenInstanceError` is raised

### Requirement: ParamConstraint constraint-shape invariant

A `ParamConstraint` SHALL hold exactly one of `value` or `range` as non-`None`. The `value` form is used for the scalar comparisons (`min`, `max`, `eq`); the `range` form is used for the range comparisons (`contains`, `between`). IF both are `None`, or both are non-`None`, construction SHALL raise `ValueError`.

#### Scenario: Neither value nor range is rejected

- **WHEN** a `ParamConstraint` is constructed with `value=None` and `range=None`
- **THEN** a `ValueError` is raised

#### Scenario: Both value and range is rejected

- **WHEN** a `ParamConstraint` is constructed with both `value` and `range` set
- **THEN** a `ValueError` is raised

#### Scenario: Exactly one of value or range is accepted

- **WHEN** a `ParamConstraint` is constructed with only `value` set (or only `range` set)
- **THEN** construction succeeds

### Requirement: Model field and enumeration contract

The shared models SHALL expose the following fields, and the cross-module string values SHALL be drawn from the enumerations below.

Fields:
- `ParamConstraint`: `canonical_name`, `comparison`, `value`, `range`, `unit`
- `QuerySpec`: `component_type`, `constraints` (a list of `ParamConstraint`)
- `RawValue`: `value` (a scalar or a `(low, high)` tuple), `unit`
- `Candidate`: `model`, `manufacturer`, `url`, `raw_params` (canonical-name → `RawValue`), `source`
- `ParamVerdict`: `canonical_name`, `status`, `required` (the originating `ParamConstraint`), `found` (a `RawValue` or `None`)
- `VerifiedCandidate`: `candidate`, `verdicts`, `overall`, `confidence`

Enumerations:
- `comparison`: `min`, `max`, `contains`, `eq`, `between`
- verdict `status`: `PASS`, `FAIL`, `UNKNOWN`
- `overall`: `match`, `partial`, `fail`
- `source`: `table`, `datasheet`
- `confidence`: `table`, `datasheet`, `unknown`

#### Scenario: Candidate exposes its fields

- **WHEN** a `Candidate` is constructed
- **THEN** it exposes `model`, `manufacturer`, `url`, `raw_params`, and `source`
- **AND** `raw_params` maps canonical parameter names to `RawValue` instances

#### Scenario: Verdict and verified-candidate values come from the enumerations

- **WHEN** a `ParamVerdict` is produced
- **THEN** its `status` is one of `PASS`, `FAIL`, `UNKNOWN`
- **AND** the enclosing `VerifiedCandidate.overall` is one of `match`, `partial`, `fail`
- **AND** its `confidence` is one of `table`, `datasheet`, `unknown`

### Requirement: Candidate URL is a display-only product-page link

`Candidate.url` SHALL be a human-facing **product-page** link, populated for display/report use only and never fetched programmatically. It SHALL point at the manufacturer's product page for the part rather than the datasheet PDF. Where a manufacturer exposes no per-part product page, adapters SHALL fall back to a link into the manufacturer's shared all-products / catalogue page — preferring a Scroll-to-Text-Fragment deep link (`#:~:text=<part number>`) that highlights the exact part in browsers that support text fragments, and otherwise simply loads the catalogue page. Per-manufacturer URL specifics live in the **manufacturer-adapters** capability.

#### Scenario: URL is the product page, not the datasheet

- **WHEN** an adapter builds a `Candidate` for a part whose manufacturer exposes a per-part product page
- **THEN** its `url` is that product page, not the datasheet PDF

#### Scenario: URL falls back to the shared catalogue page

- **WHEN** an adapter builds a `Candidate` for a part whose manufacturer exposes no per-part product page
- **THEN** its `url` is a link into the manufacturer's shared all-products / catalogue page (preferring a `#:~:text=<part number>` highlight deep link)

#### Scenario: URL is display-only

- **WHEN** a `Candidate.url` is produced
- **THEN** it is used for human display / reporting only and is never fetched programmatically
