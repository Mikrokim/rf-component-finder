# Parameter Ontology Specification

## Purpose

Define the central, code-defined dictionary of measurable RF parameters and the registry of component types. The ontology is the single source of truth that the form (field generation), the adapter (column mapping), and the verifier (comparison) read from. This spec documents the behavior **as currently implemented** in `rf_finder/ontology/parameters.py` and `rf_finder/ontology/components.py`.

## Requirements

### Requirement: Central parameter dictionary

The system SHALL maintain a central `PARAMETERS` dictionary keyed by canonical parameter name. Each entry SHALL be an immutable `ParamDef` carrying: `label` (human-readable name), `canonical_unit`, `units` (the accepted unit strings with the canonical unit listed first), `comparison` (the verifier rule), `applies_to` (the component types the parameter is relevant to), and `single_value_ok` (a boolean, default `False`) — for a `contains` parameter, whether the form also accepts a **single** entered value (stored as the degenerate point `(v, v)`) in addition to a full range.

The dictionary SHALL define exactly these ten parameters, each applicable to `amplifier`:

| name | label | canonical_unit | units | comparison |
|------|-------|----------------|-------|------------|
| `freq_range` | `Frequency range` | `GHz` | `["GHz", "MHz"]` | `contains` |
| `P1dB` | `P1dB (output 1 dB compression)` | `dBm` | `["dBm", "W", "mW"]` | `min` |
| `Gain` | `Gain` | `dB` | `["dB"]` | `min` |
| `NF` | `Noise figure` | `dB` | `["dB"]` | `max` |
| `IP3` | `IP3` | `dBm` | `["dBm"]` | `min` |
| `Psat` | `Saturated power (Psat)` | `dBm` | `["dBm", "W", "mW"]` | `min` |
| `VDD` | `Supply voltage (VDD)` | `V` | `["V"]` | `contains` |
| `length` | `Length` | `mm` | `["mm", "mil", "cm", "inch"]` | `max` |
| `width` | `Width` | `mm` | `["mm", "mil", "cm", "inch"]` | `max` |
| `MSL` | `MSL level (1–5)` | `""` (dimensionless) | `[""]` | `max` |
| `Temperature` | `Operating temperature` | `degC` | `["degC"]` | `contains` |

`freq_range.applies_to` SHALL be `["amplifier", "mixer", "filter", "attenuator"]`; all other parameters SHALL apply to `["amplifier"]` only.

Exactly one parameter SHALL carry `single_value_ok = True`: `VDD` — a `contains` parameter whose form additionally accepts a single value ("must operate at exactly this voltage"), stored as the degenerate point `(v, v)`. All other parameters SHALL have `single_value_ok = False`; in particular the band-only `contains` parameters `freq_range` and `Temperature` are always bands and require both bounds.

#### Scenario: Amplifier parameter set and rules

- **WHEN** the `PARAMETERS` dictionary is read
- **THEN** it contains exactly the eleven entries `freq_range`, `P1dB`, `Gain`, `NF`, `IP3`, `Psat`, `VDD`, `length`, `width`, `MSL`, `Temperature`
- **AND** their `comparison` values are `contains`, `min`, `min`, `max`, `min`, `min`, `contains`, `max`, `max`, `max`, `contains` respectively
- **AND** their `canonical_unit` values are `GHz`, `dBm`, `dB`, `dB`, `dBm`, `dBm`, `V`, `mm`, `mm`, `""`, `degC` respectively
- **AND** `VDD.single_value_ok` is `True` and every other parameter's `single_value_ok` is `False`

#### Scenario: Canonical unit listed first in the units list

- **WHEN** a parameter's `units` list is read
- **THEN** the first element equals that parameter's `canonical_unit`
- **AND** for `freq_range` the `units` list is exactly `["GHz", "MHz"]`

### Requirement: Component type registry

The system SHALL maintain a `COMPONENTS` dictionary of known component types, each mapping to at least a display `label`. The currently registered component SHALL be `amplifier` with label `Amplifier`. The system SHALL expose `component_labels()` returning a `{canonical_name: label}` mapping for every registered component.

#### Scenario: Registered components and labels

- **WHEN** `component_labels()` is called
- **THEN** it returns `{"amplifier": "Amplifier"}`

### Requirement: Parameter lookup by component type

The system SHALL provide `params_for(component_type)` that returns the subset of `PARAMETERS` whose `applies_to` includes `component_type`. For an unknown component type the function SHALL return an empty dictionary (never `None`).

#### Scenario: Amplifier returns its eleven parameters

- **WHEN** `params_for("amplifier")` is called
- **THEN** the returned keys are exactly `{freq_range, P1dB, Gain, NF, IP3, Psat, VDD, length, width, MSL, Temperature}`
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
