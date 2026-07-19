## ADDED Requirements

### Requirement: Requested supply-voltage names are matched under vendor wording

The system SHALL recognise a datasheet's supply-voltage wording as satisfying a request for a canonical supply name, via an alias map (`VDD` → `Drain Voltage`, `Vds`, `Drain to Source Voltage`; `VCC` → `Vcc`, `Collector Voltage`). A requested name's aliases SHALL be made available to the extraction so the value is found under the vendor's term. A requested name with no aliases is unaffected.

#### Scenario: VDD is found under "Drain Voltage"

- **WHEN** `VDD` is requested and the datasheet states `Drain Voltage … 28 V` (not the literal "VDD")
- **THEN** `VDD` resolves to `{"unit": "V", "typ": 28}`, not `{}` or null

#### Scenario: A name without aliases is unchanged

- **WHEN** a requested name has no alias-map entry
- **THEN** it is extracted exactly as today, with no alias injected

### Requirement: An absent keyword-grounded parameter is never fabricated

For a requested keyword-grounded categorical parameter — `MSL` (keywords `msl`, `moisture`) and `package` (keywords `package`, `pkg`, `case`, `outline`, `body`) — the result SHALL be `null` unless one of that parameter's keywords appears (case-insensitively) in the fed datasheet text, regardless of what the model returned. The keyword lists are derived from the surveyed vendors; `jedec` is deliberately excluded from `MSL` because it also marks ESD and package standards.

#### Scenario: A stated MSL is kept

- **WHEN** the fed text states `Moisture Sensitivity Level MSL 1`
- **THEN** `MSL` resolves to `"1"`

#### Scenario: An absent MSL is nulled despite a model guess

- **WHEN** the fed text contains no `msl` or `moisture` keyword, but the model returned `"3"`
- **THEN** `MSL` is `null`

### Requirement: Physical size prose is decomposed into length and width

The system SHALL parse a physical-dimension pattern (`A x B unit`, tolerant of `x`/`×` and an optional repeated unit) from the datasheet text and return `length` = the FIRST dimension and `width` = the SECOND — the product-resolved convention — without relying on the model. When no such pattern is present, `length` and `width` SHALL be `null` (never guessed); the regex match is itself the grounding, so no keyword list is used for size.

#### Scenario: Die size is decomposed

- **WHEN** the fed text states `Die size: 4530 µm x 6090 µm`
- **THEN** `length` resolves to `4530` µm and `width` to `6090` µm

#### Scenario: No dimension pattern gives null

- **WHEN** the fed text contains no `A x B` dimension pattern
- **THEN** `length` and `width` are `null`
