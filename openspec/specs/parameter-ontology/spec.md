# Parameter Ontology Specification

## Purpose

Define the central, code-defined dictionary of measurable RF parameters and the registry of component types. The ontology is the single source of truth that the form (field generation), the adapter (column mapping), and the verifier (comparison) read from. This spec documents the behavior **as currently implemented** in `rf_finder/ontology/parameters.py` and `rf_finder/ontology/components.py`.

## Requirements

### Requirement: Central parameter dictionary

The system SHALL maintain a central `PARAMETERS` dictionary keyed by canonical parameter name. Each entry SHALL be an immutable `ParamDef` carrying: `label` (human-readable name), `canonical_unit`, `units` (the accepted unit strings with the canonical unit listed first), `comparison` (the verifier rule), and `applies_to` (the component types the parameter is relevant to).

Each parameter's `units` SHALL be **derived** from its `canonical_unit` via `units_for` (in `rf_finder.ontology.units`), which returns every source unit the converters can turn into that canonical unit, canonical first. A canonical unit with no alternative-unit converter (`V`, `mm`, `degC`, `""`) SHALL yield `[canonical_unit]`. This keeps the accepted units in lock-step with the conversion engine — adding a converter automatically widens the corresponding form selector, with no hand-maintained list to drift.

The dictionary SHALL define exactly these ten parameters, each applicable to `amplifier`:

| name | label | canonical_unit | units | comparison |
|------|-------|----------------|-------|------------|
| `freq_range` | `Frequency range` | `GHz` | `["GHz", "MHz", "kHz", "Hz"]` | `contains` |
| `P1dB` | `P1dB (output 1 dB compression)` | `dBm` | `["dBm", "W", "mW"]` | `min` |
| `Gain` | `Gain` | `dB` | `["dB"]` | `min` |
| `NF` | `Noise figure` | `dB` | `["dB"]` | `max` |
| `IP3` | `IP3` | `dBm` | `["dBm", "W", "mW"]` | `min` |
| `Psat` | `Saturated power (Psat)` | `dBm` | `["dBm", "W", "mW"]` | `min` |
| `VDD` | `Supply voltage (VDD)` | `V` | `["V"]` | `contains` |
| `Size` | `Size` | `mm` | `["mm"]` | `max` |
| `MSL` | `MSL level (1–5)` | `""` (dimensionless) | `[""]` | `max` |
| `Temperature` | `Operating temperature` | `degC` | `["degC"]` | `contains` |

`freq_range.applies_to` SHALL be `["amplifier", "mixer", "filter", "attenuator"]`; all other parameters SHALL apply to `["amplifier"]` only.

#### Scenario: Amplifier parameter set and rules

- **WHEN** the `PARAMETERS` dictionary is read
- **THEN** it contains exactly the ten entries `freq_range`, `P1dB`, `Gain`, `NF`, `IP3`, `Psat`, `VDD`, `Size`, `MSL`, `Temperature`
- **AND** their `comparison` values are `contains`, `min`, `min`, `max`, `min`, `min`, `contains`, `max`, `max`, `contains` respectively
- **AND** their `canonical_unit` values are `GHz`, `dBm`, `dB`, `dB`, `dBm`, `dBm`, `V`, `mm`, `""`, `degC` respectively

#### Scenario: Units are derived from the converters, canonical first

- **WHEN** a parameter's `units` list is read
- **THEN** the first element equals that parameter's `canonical_unit`
- **AND** for `freq_range` the `units` list is exactly `["GHz", "MHz", "kHz", "Hz"]`
- **AND** every `dBm` parameter (including `IP3`) offers `["dBm", "W", "mW"]`
- **AND** a parameter whose canonical unit has no alternative-unit converter offers only `[canonical_unit]`

#### Scenario: Every offered unit is convertible

- **WHEN** any unit in a parameter's `units` list is passed to `to_canonical` with that parameter's `canonical_unit`
- **THEN** the conversion succeeds (no offered unit can be one the verifier cannot convert)

### Requirement: Component type registry

The system SHALL maintain a `COMPONENTS` dictionary of known component types, each mapping to at least a display `label`. The currently registered component SHALL be `amplifier` with label `Amplifier`. The system SHALL expose `component_labels()` returning a `{canonical_name: label}` mapping for every registered component.

#### Scenario: Registered components and labels

- **WHEN** `component_labels()` is called
- **THEN** it returns `{"amplifier": "Amplifier"}`

### Requirement: Parameter lookup by component type

The system SHALL provide `params_for(component_type)` that returns the subset of `PARAMETERS` whose `applies_to` includes `component_type`. For an unknown component type the function SHALL return an empty dictionary (never `None`).

#### Scenario: Amplifier returns its ten parameters

- **WHEN** `params_for("amplifier")` is called
- **THEN** the returned keys are exactly `{freq_range, P1dB, Gain, NF, IP3, Psat, VDD, Size, MSL, Temperature}`
- **AND** every returned value is a `ParamDef`

#### Scenario: Unknown component returns an empty dictionary

- **WHEN** `params_for("thereallyunknowntype")` is called
- **THEN** the result is an empty dictionary
- **AND** the result is not `None`

### Requirement: Parameter definitions are immutable

`ParamDef` SHALL be an immutable value (implemented as a `NamedTuple`); attempting to reassign one of its fields SHALL raise an error.

#### Scenario: Mutating a parameter definition is rejected

- **WHEN** code attempts to assign a new value to a field of an entry in `PARAMETERS` (e.g. `PARAMETERS["Gain"].label = "modified"`)
- **THEN** an `AttributeError` or `TypeError` is raised
