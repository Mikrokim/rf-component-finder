## ADDED Requirements

### Requirement: Deterministic extraction returns a value or explicit absence

The system SHALL extract TEMPERATURE, SIZE, and MSL from datasheet text using
pure regular expressions with no model call, and SHALL return `None` when the
value is not present in the text rather than a guessed value. Given identical
input text, the extractors SHALL return identical output.

#### Scenario: Value present is extracted

- **WHEN** `temp_range` is given text containing "Operating Temperature -40 to +85 °C"
- **THEN** it returns `(-40, 85)`

#### Scenario: Value absent returns None, not a guess

- **WHEN** `size_dims` is given text that contains no `A×B` physical dimension
- **THEN** it returns `None`

#### Scenario: Deterministic across calls

- **WHEN** an extractor is called twice on the same text
- **THEN** both calls return the same result

### Requirement: Operating temperature range extraction

`temp_range` SHALL return the operating temperature as `(min, max)`, selecting the
operating range and never the storage range. It SHALL match the operating label in
its common forms (`operating`/`operation` `temperature`/`range`, including
`case`/`junction`/`ambient` qualifiers and the abbreviation `Temp.`). When no
operating label is present it SHALL fall back to a bare `Temperature Range` only
when that label's left context is not a storage/junction/mounting/reflow label.
It SHALL normalize the PDF private-use degree glyph `U+F0B0` to `°`, accept a
number only when it is signed or immediately adjacent to a temperature unit, and
treat en dash and em dash as a minus sign. When the range is stated as two
separate labels (`Maximum Operating Temperature N` and `Minimum Operating
Temperature M`) rather than `A to B`, it SHALL pair those two labelled values and
SHALL NOT let an adjacent Storage value leak into the range.

#### Scenario: Split Maximum/Minimum Operating Temperature labels

- **WHEN** the text contains "Maximum Operating Temperature 85 °C Maximum Storage Temperature 125 °C Minimum Operating Temperature -54 °C"
- **THEN** `temp_range` returns `(-54, 85)` and not `(85, 125)`

#### Scenario: Storage range is excluded

- **WHEN** the text contains both "Operating Temperature -40 to +85 °C" and "Storage Temperature -55 to +135 °C"
- **THEN** `temp_range` returns `(-40, 85)`

#### Scenario: Column format without the word "to"

- **WHEN** the text contains "Operating Temperature (package base). TPKG BASE -40 105 °C"
- **THEN** `temp_range` returns `(-40, 105)`

#### Scenario: Footnote superscript is not read as a bound

- **WHEN** the text contains "Operating Temperature5 -40°C to +85°C"
- **THEN** `temp_range` returns `(-40, 85)` and not `(-40, 5)`

#### Scenario: En dash is a minus sign

- **WHEN** the text contains "Operating temperature –55 °C to +85 °C"
- **THEN** `temp_range` returns `(-55, 85)` and not `(55, 85)`

#### Scenario: Bare "Temperature Range" fallback when not storage

- **WHEN** the text has no operating label but contains "Temperature Range -40°C to +125°C" with a non-storage left context
- **THEN** `temp_range` returns `(-40, 125)`

### Requirement: Physical size extraction

`size_dims` SHALL return the physical part size as `(a, b)` from an `A×B` pattern,
accepting a candidate only when its context contains a length unit
(mm/µm/mils/inch, including curly-quote inches) or a size keyword
(package/die/chip/size), and rejecting candidates whose context contains a
distractor (thru-hole, diameter, tolerance, bond pad, MTTF, hours, `×10`), an
eval-board bill-of-materials / discrete-component marker (a `CAP`/capacitor label
or a capacitance value such as `µF`/`nF`/`pF`), or a zero dimension.

#### Scenario: Bill-of-materials capacitor dimension is rejected

- **WHEN** the only `A×B` in the text is an eval-board part row "CAP, 3300 uF, ±20%, 100V, 0.98x1.97in" and no product size is stated
- **THEN** `size_dims` returns `None`

#### Scenario: Package size is selected over a bond-pad dimension

- **WHEN** the text contains "Chip size: 2.32 X 1.23 X 0.10mm" alongside bond-pad callouts like "85x85"
- **THEN** `size_dims` returns `(2.32, 1.23)`

#### Scenario: Scientific-notation distractor is rejected

- **WHEN** the only `A×B` in the text is "MTTF > 1 x 106 hours" and no physical size is stated
- **THEN** `size_dims` returns `None`

#### Scenario: Pin-count "Pad" is not treated as a bond pad

- **WHEN** the text contains "24 Pad 5 x 3 mm Laminate Package"
- **THEN** `size_dims` returns `(5.0, 3.0)`

### Requirement: MSL level extraction

`msl_level` SHALL return the moisture sensitivity level as a string, anchoring on
`moisture sensitivity`/`MSL` and selecting the first standalone 1–6 digit, so that
a digit embedded in a larger number (such as a reflow temperature 260 or 150) is
not returned as the level.

#### Scenario: Explicit level is returned

- **WHEN** the text contains "Moisture Sensitivity Level MSL 1"
- **THEN** `msl_level` returns `"1"`

#### Scenario: Reflow temperature is not read as the level

- **WHEN** the text contains "Peak Reflow (Moisture Sensitivity Level 260°C" and elsewhere "(MSL) 3"
- **THEN** `msl_level` returns `"3"` and not `"2"`

#### Scenario: Absent MSL returns None

- **WHEN** the text contains no `moisture sensitivity`/`MSL` mention
- **THEN** `msl_level` returns `None`
