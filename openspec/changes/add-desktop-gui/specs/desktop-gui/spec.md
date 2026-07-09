## ADDED Requirements

### Requirement: Desktop window entry point

The system SHALL provide a Tkinter desktop application launchable with `python -m rf_finder.ui.gui`. Launching it SHALL open a single window titled for the tool and configure the shared response-cache provider exactly as the CLI does (`cache.configure(load_cache_config())`) before any search runs. The existing `python -m rf_finder` CLI SHALL remain available and unchanged; the GUI is an additive, alternative entry point.

#### Scenario: Window launches with cache configured

- **WHEN** the user runs `python -m rf_finder.ui.gui`
- **THEN** a single application window opens with the component-type selector and an empty results area
- **AND** the response-cache provider has been configured from `load_cache_config()` before the first search

#### Scenario: CLI is unaffected

- **WHEN** the GUI module is added
- **THEN** `python -m rf_finder` still runs the existing interactive terminal flow with no behavioral change

### Requirement: Ontology-driven form rendered from the selected component type

The window SHALL present a component-type selector populated from the ontology `COMPONENTS`, defaulting to `amplifier`. For the selected type the window SHALL render one input group per field returned by `build_form(component_type)`, preserving that function's field order. A range field (`comparison` in `contains` / `between` / `min` / `max`) SHALL render a min entry and a max entry; a scalar field (`eq`) SHALL render a single value entry. Every field SHALL render a unit selector offering `field.units` with the canonical unit (`field.units[0]`) selected by default. Changing the selected component type SHALL rebuild the form to the new type's fields, discarding the previous type's entries.

#### Scenario: Amplifier form is rendered from build_form

- **WHEN** the component type is `amplifier`
- **THEN** the form shows one input group per field of `build_form("amplifier")`, in the same order
- **AND** each range field shows a min and a max entry, each scalar field shows one value entry, and each field shows a unit selector defaulting to its canonical unit

#### Scenario: Changing component type rebuilds the form

- **WHEN** the user selects a different component type in the selector
- **THEN** the form is rebuilt from `build_form(<new type>)` and the previous type's entered values are cleared

#### Scenario: Only ontology types are offered

- **WHEN** the component-type selector is populated
- **THEN** its choices are exactly the keys of the ontology `COMPONENTS`

### Requirement: Form values collected through the existing answers seam

On search, the window SHALL read the entered widgets into an `answers` dict using the established key convention — `"<name>.min"`, `"<name>.max"`, `"<name>.unit"` for range fields and `"<name>.value"`, `"<name>.unit"` for scalar fields — and obtain the `QuerySpec` by calling `collect(schema, answers=answers)`. Empty entries SHALL be omitted (or left empty) so that, per the existing `collect` contract, they produce no constraint. The GUI SHALL NOT reimplement constraint parsing, unit validation, or range logic; it SHALL delegate all of it to `collect`.

#### Scenario: Filled fields become a QuerySpec via collect

- **WHEN** the user enters `freq_range` min `2`, max `6`, unit `GHz` and `P1dB` min `26`, unit `dBm`, and clicks Search
- **THEN** the window builds `answers` with keys `freq_range.min=2`, `freq_range.max=6`, `freq_range.unit=GHz`, `P1dB.min=26`, `P1dB.unit=dBm`
- **AND** the `QuerySpec` used for the search is the result of `collect(schema, answers=answers)`

#### Scenario: Empty fields yield no constraints

- **WHEN** the user clicks Search without entering any field
- **THEN** `collect` is called with no filled keys and the resulting `QuerySpec` has an empty `constraints` list

### Requirement: Search runs without freezing the window

The window SHALL execute the search (each supporting adapter's `search(spec)` followed by `verify(spec, candidate)` for every candidate) on a background thread so the UI thread never blocks during the multi-second fetch. While a search is in progress the window SHALL show a loading indication and SHALL prevent a second concurrent search from being started. Results SHALL be applied to the table on the UI thread once the background work completes.

#### Scenario: UI stays responsive during a search

- **WHEN** the user clicks Search and adapters are being fetched
- **THEN** the window remains responsive and shows a loading state
- **AND** the Search action cannot be triggered again until the in-progress search finishes

#### Scenario: Adapter selection matches the CLI

- **WHEN** a search runs for a component type
- **THEN** only adapters whose `supported_components` include that type are queried, as in the CLI flow
- **AND** each candidate is passed through `verify(spec, candidate)` to obtain its verdict

### Requirement: Matching components shown in a table with browser deep-links

The table SHALL display only the components whose overall verdict is `match`; `partial` and `fail` candidates SHALL be screened out of the table. It SHALL show at most `max_results` (a configurable cap, default 10, loaded from `config.yaml`) matches; when more exist, the window SHALL indicate that only the top `max_results` of the total are shown so the user knows to narrow the filters. The table SHALL have columns model, manufacturer, verdicts, and url. Double-clicking a row SHALL open that candidate's url in the system web browser. When a search yields no `match` candidates, the window SHALL display an explicit "no matching components" indication (including the number screened) rather than an empty table with no explanation.

#### Scenario: Only matches are listed; the rest are screened out

- **WHEN** a search yields a mix of match, partial, and fail candidates
- **THEN** the table lists only the `match` candidates (at most 10)

#### Scenario: More than ten matches shows only the top ten

- **WHEN** a search yields more than 10 `match` candidates
- **THEN** the table shows exactly 10 rows
- **AND** the window indicates the total number of matches and that only the top 10 are shown

#### Scenario: Row opens the datasheet url

- **WHEN** the user double-clicks a result row
- **THEN** that candidate's url is opened in the system web browser

#### Scenario: No matching components found

- **WHEN** a search returns candidates but none with overall verdict `match`
- **THEN** the window shows an explicit "no matching components" indication with the number screened

### Requirement: Numeric fields reject non-numeric input as it is typed

Every value entry (min, max, and scalar value) SHALL accept only characters that form a number in progress (digits, an optional leading `-`, and a single `.`); a keystroke that would make the field non-numeric SHALL be rejected so it never appears. Unit selectors are fixed dropdowns and cannot take a free-typed value.

#### Scenario: Letters cannot be typed into a value field

- **WHEN** the user types a letter into a min/max/value entry
- **THEN** the keystroke is rejected and the field keeps only numeric text

### Requirement: A `contains` field requires both bounds before searching

Because a `contains` parameter (e.g. frequency range) describes a band, a one-sided entry is meaningless. Before searching, IF a `contains` field has exactly one of its min/max filled, the window SHALL report an error naming that field and SHALL NOT run the search — rather than silently dropping the half-entered constraint. A `between`/`min`/`max` field MAY be left one-sided (an open-ended bound) and SHALL NOT trigger this error.

#### Scenario: Half-filled contains range is rejected

- **WHEN** the user fills only the minimum of a `contains` field (e.g. frequency range) and clicks Search
- **THEN** the window shows an error naming that field and does not run the search

#### Scenario: One-sided between range is allowed

- **WHEN** the user fills only the minimum of a `between` field (e.g. gain) and clicks Search
- **THEN** no validation error is raised for that field and the search runs

### Requirement: Invalid input is reported without crashing

When `collect` raises `ValueError` (for example a min greater than max), the window SHALL catch it and present the message in a dialog, leaving the form intact for correction, and SHALL NOT close or crash.

#### Scenario: Bad input surfaces as a dialog

- **WHEN** the user enters a min greater than the max and clicks Search
- **THEN** the `ValueError` from `collect` is caught and its message is shown in a dialog
- **AND** the window stays open with the entered values preserved for correction
