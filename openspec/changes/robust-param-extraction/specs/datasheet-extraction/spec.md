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

### Requirement: The model's size answer is split into length and width

When `length` or `width` is requested, the system SHALL request the whole `size` from the model — which selects the product's size more reliably than length/width directly — and split the model's answer into `length` = the FIRST dimension and `width` = the SECOND (the product-resolved convention). The size selected SHALL follow the sold-form priority for component replacement: **(1) the package** (body / outline / case) when stated; **(2) the die** when there is no package (the part is sold bare); **(3) null** when neither is stated. The split SHALL read an `A x B` string (tolerant of `x`/`×` and an optional repeated unit) in the model's `value`, else its `min`/`max` pair. The resulting pair SHALL be grounded against the datasheet text: kept only if those two numbers occur as a real dimension pair in the text, so a fabricated size is nulled. `length`/`width` SHALL be `null` when nothing usable and grounded is found; the internally-requested `size` SHALL NOT be returned to the caller.

**Selection basis — now vs later.** The current basis is **how the part is sold** (the sold form: package-first, then die, as above) — the size relevant to replacing the part as it ships. A later need MAY be to search by the **exposed / bare die** size even when a package is stated; the system MAY expose that as an optional mode, with the sold form remaining the default. It is an available option to add when required, not a committed change.

#### Scenario: The die size is selected over the pad size

- **WHEN** the text holds both a die size `4530 µm x 6090 µm` and a pad size `90 x 90 µm`, and the model returns `size` = `4530 µm x 6090 µm`
- **THEN** `length` resolves to `4530` µm and `width` to `6090` µm

#### Scenario: A fabricated size absent from the text is nulled

- **WHEN** the model returns `size` `"9.00 x 8.00 mm"`, which does not occur in the datasheet text
- **THEN** `length` and `width` are `null`

#### Scenario: The internal size request is not leaked

- **WHEN** the caller requests only `length` and `width`
- **THEN** the result contains exactly `length` and `width`, not `size`
