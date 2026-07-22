# Unit Conversion Specification

## Purpose

Define the pure, side-effect-free unit conversions used to normalize parameter values to their canonical units before comparison. This spec documents the behavior **as currently implemented** in `rf_finder/ontology/units.py` via the single public function `to_canonical(value, from_unit, canonical)`. The supported canonical units are `GHz` (frequency), `dBm` (power), `dB` (dimensionless ratio), and `mm` (length).

## Requirements

### Requirement: Identity conversion short-circuit

WHEN `from_unit` equals `canonical`, the system SHALL return `value` unchanged without performing any arithmetic. This SHALL hold for any unit string (including non-canonical units such as `MHz`→`MHz`) and SHALL allow open bounds and zero to pass through without triggering a logarithm.

#### Scenario: Same source and canonical unit returns the value unchanged

- **WHEN** `to_canonical(2400.0, "MHz", "MHz")` is called
- **THEN** it returns `2400.0`

#### Scenario: Open and zero bounds pass through identity

- **WHEN** `to_canonical(float("inf"), "dBm", "dBm")` is called
- **THEN** it returns `inf`
- **AND WHEN** `to_canonical(0.0, "dBm", "dBm")` is called, it returns `0.0` (no `log10(0)`)

### Requirement: Frequency conversion to GHz

WHEN `canonical` is `GHz`, the system SHALL convert from `Hz`, `kHz`, `MHz`, or `GHz` to GHz using fixed factors (`Hz`=1e-9, `kHz`=1e-6, `MHz`=1e-3, `GHz`=1.0). IF `from_unit` is not one of these frequency units, the system SHALL raise `ValueError` whose message contains "Unknown frequency unit".

#### Scenario: MHz converts to GHz

- **WHEN** `to_canonical(6000.0, "MHz", "GHz")` is called
- **THEN** it returns `6.0`

#### Scenario: Hz and kHz convert to GHz

- **WHEN** `to_canonical(1_000_000_000.0, "Hz", "GHz")` is called
- **THEN** it returns `1.0`
- **AND WHEN** `to_canonical(1_000_000.0, "kHz", "GHz")` is called, it returns `1.0`

#### Scenario: Unknown frequency unit is rejected

- **WHEN** `to_canonical(1.0, "THz", "GHz")` is called
- **THEN** a `ValueError` containing "Unknown frequency unit" is raised

### Requirement: Power conversion to dBm

WHEN `canonical` is `dBm`, the system SHALL convert power as follows: `dBm` is the identity; `mW` converts via `10 * log10(mW)`; `W` converts by multiplying by 1000 then `10 * log10(mW)`. IF the input power in mW is non-positive (`<= 0`), the system SHALL raise `ValueError` whose message contains "non-positive". IF `from_unit` is not a recognized power unit, the system SHALL raise `ValueError` whose message contains "Unknown power unit".

#### Scenario: Milliwatts and watts convert to dBm

- **WHEN** `to_canonical(1000.0, "mW", "dBm")` is called
- **THEN** it returns `30.0`
- **AND WHEN** `to_canonical(1.0, "W", "dBm")` is called, it returns `30.0`
- **AND WHEN** `to_canonical(1.0, "mW", "dBm")` is called, it returns `0.0`

#### Scenario: Non-positive power is rejected

- **WHEN** `to_canonical(0.0, "mW", "dBm")` or `to_canonical(-1.0, "mW", "dBm")` is called
- **THEN** a `ValueError` containing "non-positive" is raised

#### Scenario: Unknown power unit is rejected

- **WHEN** `to_canonical(1.0, "uW", "dBm")` is called
- **THEN** a `ValueError` containing "Unknown power unit" is raised

### Requirement: Dimensionless ratio conversion to dB

WHEN `canonical` is `dB`, the system SHALL treat the conversion as the identity for a `dB` source value (which may be negative or zero, e.g. gain or noise figure). IF `from_unit` is anything other than `dB`, the system SHALL raise `ValueError` whose message contains "Unknown ratio unit".

#### Scenario: dB values pass through unchanged

- **WHEN** `to_canonical(18.0, "dB", "dB")` is called
- **THEN** it returns `18.0`
- **AND WHEN** `to_canonical(-3.5, "dB", "dB")` is called, it returns `-3.5`

#### Scenario: Non-dB source unit for a dB canonical is rejected

- **WHEN** `to_canonical(10.0, "dBm", "dB")` is called
- **THEN** a `ValueError` containing "Unknown ratio unit" is raised

### Requirement: Length conversion to mm

WHEN `canonical` is `mm`, the system SHALL convert a length by multiplying by a fixed linear factor: `mm` → `×1`, `cm` → `×10`, `inch` → `×25.4`, `mil` → `×0.0254`. IF `from_unit` is not one of these, the system SHALL raise `ValueError` whose message contains "Unknown length unit".

#### Scenario: Length units convert to mm

- **WHEN** `to_canonical(1.0, "cm", "mm")` is called
- **THEN** it returns `10.0`
- **AND WHEN** `to_canonical(1.0, "inch", "mm")` is called, it returns `25.4`
- **AND WHEN** `to_canonical(40.0, "mil", "mm")` is called, it returns `1.016`

#### Scenario: Unknown length unit is rejected

- **WHEN** `to_canonical(1.0, "ft", "mm")` is called
- **THEN** a `ValueError` containing "Unknown length unit" is raised

### Requirement: Unsupported canonical unit

IF `canonical` is not one of `GHz`, `dBm`, `dB`, or `mm` (and differs from `from_unit`), the system SHALL raise `ValueError` whose message contains "Unsupported canonical unit".

#### Scenario: Unsupported canonical unit is rejected

- **WHEN** `to_canonical(1.0, "MHz", "Hz")` is called
- **THEN** a `ValueError` containing "Unsupported canonical unit" is raised
- **AND WHEN** `to_canonical(1.0, "W", "dBW")` is called, the same error is raised
