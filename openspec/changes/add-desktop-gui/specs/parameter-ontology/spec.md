## MODIFIED Requirements

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
