## ADDED Requirements

### Requirement: Feed fits the model context window

The extractor SHALL reduce the datasheet to a subset of pages or text regions
before sending it to the model, so that each prompt (instruction + feed +
requested parameters) fits within the provider's configured context window. The
extractor SHALL NOT send the whole datasheet text when doing so would overflow
the window and cause the provider to silently truncate the prompt.

#### Scenario: Large datasheet does not overflow

- **WHEN** a datasheet whose whole text plus instruction exceeds the provider
  context window is extracted
- **THEN** the feed sent to the model is a reduced subset that fits within the
  window, and no parameter is nulled solely because its value was truncated away

#### Scenario: Small datasheet is unaffected

- **WHEN** a datasheet whose whole text already fits the window is extracted
- **THEN** extraction still returns the requested parameters correctly

### Requirement: VDD is extracted from selected spec pages

VDD SHALL be extracted from only the PDF pages selected as spec pages. A page
SHALL be selected when it satisfies a low graph-marker density AND at least one
of: it contains a Min/Typ/Max value table; it contains an absolute-maximum /
max-rating table; or it states a supply/drain/bias voltage together with a
value. Pages that state a supply voltage only as a graph condition or axis label
SHALL NOT qualify on that basis.

#### Scenario: Operating and absolute-max pages are both selected

- **WHEN** a datasheet states the operating supply voltage on one page and the
  absolute-maximum drain voltage on another
- **THEN** both pages are included in the VDD feed so the model can place the
  operating value as typ and the absolute-maximum value as max

#### Scenario: Chart pages carrying a running spec header are excluded

- **WHEN** a vendor repeats a spec-section header on every page, including chart
  pages with a high graph-marker count
- **THEN** the chart pages are excluded from the VDD feed and only the real spec
  pages are selected

#### Scenario: Prose supply statement selects its page

- **WHEN** the operating supply voltage appears only as prose in a features block
  (for example "Power Supply: +5V") with no Min/Typ/Max table on that page
- **THEN** that page is still selected for the VDD feed by the supply-voltage
  signal

### Requirement: VDD is extracted in an isolated call

VDD SHALL be requested from the model on its own, not grouped with other
requested parameters, to preserve correct typ/max placement.

#### Scenario: Isolated VDD keeps placement

- **WHEN** VDD is requested together with the operating and absolute-maximum
  values available in the feed
- **THEN** VDD is extracted in a call whose only requested parameter is VDD, and
  the operating value lands in typ and the absolute-maximum value in max

### Requirement: VDD value maps to the six fields by its stated shape

The single most-appropriate VDD figure SHALL be recorded according to the shape
in which it is stated in the text, and no spurious extra values (graph
conditions, axis labels, repeated mentions) SHALL be added. The mapping is:

- a **list of discrete values** (for example `2.7, 5, 6`) → `value`
- a **range** (for example `4.5 to 5.5`, `4.5–5.5`) → `min` and `max`
- a **single value** → `typ`
- a **maximum-only** statement (for example "maximum 6.5 V") → `max`
- a **minimum-only** statement (for example "minimum 5 V") → `min`

#### Scenario: Discrete list goes to value

- **WHEN** the datasheet lists several selectable supply voltages such as
  `2.7 V, 5 V, 6 V`
- **THEN** those figures are recorded in `value` and `typ`/`min`/`max` are not
  fabricated from them

#### Scenario: Range goes to min and max

- **WHEN** the supply voltage is stated as a range such as `4.5 to 5.5 V`
- **THEN** `min` is 4.5 and `max` is 5.5 and `value` stays empty

#### Scenario: Single value goes to typ

- **WHEN** the supply voltage is stated as one operating figure with no range or
  list (for example `Power Supply: +5V`)
- **THEN** the figure is recorded in `typ` and no other numeric field is filled

#### Scenario: Bound-only statement goes to that bound

- **WHEN** only an absolute-maximum drain voltage (for example "maximum 6.5 V")
  or only a minimum is stated
- **THEN** the figure is recorded in `max` (or `min`) respectively and the other
  bounds are left empty

#### Scenario: No spurious extras

- **WHEN** the feed also contains the same voltage repeated as a graph condition
  or axis label
- **THEN** the recorded VDD value is not duplicated or spread into `value`, and
  the field placement above still holds

### Requirement: SIZE, MSL and TEMPERATURE are located by regex windows

SIZE, MSL and TEMPERATURE SHALL be extracted from regex-located text windows
rather than page selection: a dimension pattern (A×B including metric, inch,
mils, or a diameter callout) for SIZE, a moisture-sensitivity keyword for MSL,
and operating/storage temperature markers for TEMPERATURE. These parameters MAY
be requested together in a single grouped call.

#### Scenario: Dimension on a separate mechanical page is located

- **WHEN** a datasheet states the die/package size only on a mechanical page that
  carries no Min/Typ/Max table
- **THEN** the dimension window is located by the SIZE regex and included in the
  feed for the grouped call

#### Scenario: Non-metric dimension is located

- **WHEN** the size is stated in inches or mils (for example `1.1" x 0.66"`)
- **THEN** the SIZE regex still locates the dimension window

### Requirement: The output contract is unchanged

The change SHALL preserve the existing extraction output contract: exactly one
key per requested parameter, each found value carrying the six fields
(unit, min, typ, max, value, condition), and not-found parameters returned as
null.

#### Scenario: Contract preserved across the split calls

- **WHEN** the isolated VDD call and the grouped SIZE/MSL/TEMPERATURE call both
  complete
- **THEN** their results are merged into a single mapping with exactly the
  requested keys and the six-field shape per found parameter
