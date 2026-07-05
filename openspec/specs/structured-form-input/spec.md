# Structured Form Input Specification

## Purpose

Define how the tool turns a structured, ontology-driven form into a `QuerySpec`. There is no free-text query and no LLM: form fields are derived from the parameter ontology, and the user's typed values become parameter constraints. This spec documents the behavior **as currently implemented** in `rf_finder/form/schema.py` (`build_form`) and `rf_finder/form/input.py` (`collect`).

## Requirements

### Requirement: Form schema generated from the ontology

The system SHALL provide `build_form(component_type) -> FormSchema`. It SHALL emit one `Field` per ontology parameter that applies to `component_type` (via `params_for`), each carrying `canonical_name`, `label`, `comparison`, `canonical_unit`, and `units` (canonical unit first). Range parameters (`comparison` in `contains` or `between`) SHALL be ordered before scalar parameters; within each group the ontology iteration order is preserved. IF `component_type` is not a registered component, the system SHALL raise `ValueError`.

#### Scenario: Amplifier form has ten fields, contains first

- **WHEN** `build_form("amplifier")` is called
- **THEN** the returned `FormSchema.component_type` is `"amplifier"` and it has exactly 10 fields
- **AND** the first three fields are the `contains` parameters `freq_range`, `VDD`, `Temperature` (in that order)
- **AND** every remaining field has `comparison != "contains"`

#### Scenario: Each field exposes canonical-first units and a label

- **WHEN** the fields of `build_form("amplifier")` are read
- **THEN** every field's `units[0]` equals its `canonical_unit`
- **AND** every field has a non-empty `label`

#### Scenario: Unknown component type is rejected

- **WHEN** `build_form("unknown_type")` is called
- **THEN** a `ValueError` is raised

### Requirement: Collecting filled fields into a QuerySpec

The system SHALL provide `collect(schema, *, answers=None) -> QuerySpec`. When `answers` is provided it is the deterministic, non-interactive seam: range fields read keys `"<name>.min"`, `"<name>.max"`, `"<name>.unit"`; scalar fields read `"<name>.value"`, `"<name>.unit"`. Only filled fields SHALL produce a `ParamConstraint`; empty fields (missing key or empty string) SHALL be skipped. An all-empty form SHALL yield a `QuerySpec` with an empty `constraints` list.

#### Scenario: Keystone example builds the expected QuerySpec

- **WHEN** `collect` runs on the amplifier schema with answers `freq_range.min=2`, `freq_range.max=6`, `freq_range.unit=GHz`, `P1dB.min=26`, `P1dB.unit=dBm`
- **THEN** the result equals a `QuerySpec(component_type="amplifier")` whose constraints are `ParamConstraint("freq_range", "contains", value=None, range=(2.0, 6.0), unit="GHz")` and `ParamConstraint("P1dB", "between", value=None, range=(26.0, inf), unit="dBm")`

#### Scenario: All-empty form yields no constraints

- **WHEN** `collect(schema, answers={})` is called
- **THEN** the result is `QuerySpec("amplifier", constraints=[])`

#### Scenario: An empty value skips its field

- **WHEN** `collect` runs with `P1dB.min=""`, `P1dB.max=""`, `P1dB.unit="dBm"`
- **THEN** no constraint with `canonical_name == "P1dB"` is present

### Requirement: Range collection for contains, between, min, and max rules

Every parameter except `eq` SHALL be collected as a min/max range field, so the user MAY enter a min, a max, or both. For a `contains` field the system SHALL require both bounds: if only one of min/max is supplied, the field SHALL be skipped (a partial `contains` range is not a constraint). For a `between`, `min`, or `max` field either side MAY be omitted: an omitted min SHALL default to `-inf` and an omitted max to `+inf` (a one-sided, open range) — filling only the natural side of a `min`/`max` parameter reproduces its namesake bound (a `min` param with only a min ⇒ "≥ x"; a `max` param with only a max ⇒ "≤ x"), while supplying the other side caps or brackets the value. A `contains` field is emitted as a `contains` constraint; every `between`/`min`/`max` field is emitted as a (possibly one-sided) `between` constraint. In all range cases, IF the parsed min is greater than the parsed max, the system SHALL raise `ValueError`.

#### Scenario: Between with one open side

- **WHEN** `collect` runs with `P1dB.min=26`, `P1dB.unit=dBm` (no max)
- **THEN** the `P1dB` constraint has `range == (26.0, inf)`
- **AND WHEN** instead `P1dB.max=30` is given with no min, the `P1dB` constraint has `range == (-inf, 30.0)`

#### Scenario: A min-rule parameter is collected as a min/max range

- **WHEN** `collect` runs with `Gain.min=20`, `Gain.max=30`, `Gain.unit=dB`
- **THEN** the `Gain` constraint has `comparison == "between"` and `range == (20.0, 30.0)`
- **AND WHEN** only `Gain.min=20` is given, the constraint's `range == (20.0, inf)`

#### Scenario: A max-rule parameter is collected as a min/max range

- **WHEN** `collect` runs with `NF.max=3`, `NF.unit=dB` (no min)
- **THEN** the `NF` constraint has `comparison == "between"` and `range == (-inf, 3.0)`

#### Scenario: Between with neither side is skipped

- **WHEN** `collect` runs with only `P1dB.unit=dBm` and no min/max
- **THEN** no `P1dB` constraint is produced

#### Scenario: Inverted range is rejected

- **WHEN** `collect` runs with `freq_range.min=6`, `freq_range.max=2`, `freq_range.unit=GHz`
- **THEN** a `ValueError` is raised

### Requirement: Chosen unit is stored unconverted

The unit chosen on each field SHALL be stored verbatim on the `ParamConstraint`; values SHALL NOT be converted to canonical units in the form (the Verifier normalizes later). IF a supplied unit is not in the field's accepted `units`, the system SHALL raise `ValueError`. WHEN the unit key is omitted or empty, the field's canonical unit SHALL be used.

#### Scenario: Non-canonical unit stored as-is

- **WHEN** `collect` runs with `freq_range.min=2000`, `freq_range.max=6000`, `freq_range.unit=MHz`
- **THEN** the constraint's `unit == "MHz"` and `range == (2000.0, 6000.0)` (not converted to GHz)

#### Scenario: Omitted unit defaults to canonical

- **WHEN** `collect` runs with `Gain.min=10`, `Gain.max=20` and no unit key
- **THEN** the `Gain` constraint's `unit == "dB"`

#### Scenario: Invalid unit is rejected

- **WHEN** `collect` runs with `P1dB.min=26`, `P1dB.unit=Watts`
- **THEN** a `ValueError` is raised

### Requirement: Numeric validation of field values

The system SHALL reject a non-numeric min, max, or scalar value with a `ValueError`. A degenerate range where `min == max` SHALL be accepted.

#### Scenario: Non-numeric input is rejected

- **WHEN** `collect` runs with `P1dB.min=notanumber`, `P1dB.unit=dBm`
- **THEN** a `ValueError` is raised

#### Scenario: Equal min and max is accepted

- **WHEN** `collect` runs with `freq_range.min=5`, `freq_range.max=5`, `freq_range.unit=GHz`
- **THEN** the `freq_range` constraint's `range == (5.0, 5.0)`

### Requirement: Interactive collection when no answers are supplied

WHEN `collect` is called without an `answers` dict, the system SHALL prompt the user interactively for each field in schema order, using `questionary` when it is importable and falling back to the built-in `input()` otherwise. A unit selector SHALL be offered only when a field has more than one accepted unit; otherwise the canonical unit SHALL be used.

#### Scenario: Interactive path drives the same field-to-constraint logic

- **WHEN** `collect(schema)` is called with no `answers`
- **THEN** the user is prompted per field in schema order and the entered values are converted into constraints by the same rules as the `answers` seam
