# Manufacturer Adapters Specification

## Purpose

Define the pluggable adapter layer that retrieves candidate components from a manufacturer source and maps them into the tool's canonical model. Adapters only fetch and map raw values; they never judge whether a candidate matches (that is the Verifier's job). This spec documents the behavior **as currently implemented** in `rf_finder/adapters/base.py`, `rf_finder/adapters/minicircuits.py`, `rf_finder/adapters/analogdevices.py`, `rf_finder/adapters/qorvo.py`, `rf_finder/adapters/vectrawave.py`, and `rf_finder/adapters/guerrillarf.py`.

## Requirements

### Requirement: Adapter interface

The system SHALL define an abstract `Adapter` base class with class attributes `manufacturer` (a name string) and `supported_components` (the collection of component-type names the adapter handles), and an abstract method `search(spec) -> list[Candidate]`. A subclass that does not implement `search` SHALL NOT be instantiable. The `search` method SHALL raise `AdapterError` on a retrieval failure rather than crash silently, and SHALL NOT decide matches.

#### Scenario: Subclass without search cannot be instantiated

- **WHEN** a subclass of `Adapter` that does not implement `search` is instantiated
- **THEN** a `TypeError` is raised

#### Scenario: Concrete adapter can be instantiated

- **WHEN** a subclass that implements `search` is instantiated
- **THEN** the instance is an `Adapter`

### Requirement: Adapter registry and self-registration

The system SHALL maintain an `ADAPTERS` registry implemented as a dictionary keyed by `manufacturer` name. The `register` class decorator SHALL instantiate the decorated adapter class and store the instance under its `manufacturer` key, returning the class unchanged.

#### Scenario: Registering an adapter stores an instance

- **WHEN** an adapter class with `manufacturer = "AlphaCo"` is decorated with `@register`
- **THEN** `"AlphaCo"` is a key in `ADAPTERS`
- **AND** `ADAPTERS["AlphaCo"]` is an instance of that class, not the class itself

### Requirement: AdapterError carries failure context

`AdapterError` SHALL be constructed with `(manufacturer, context, cause=None)` and expose those values as attributes. Its string form SHALL include the manufacturer and context, and SHALL append the cause when one is present. Constructing it with `cause=None` SHALL NOT break stringification.

#### Scenario: Error exposes attributes and a readable message

- **WHEN** `AdapterError("Mini-Circuits", "HTTP 503", cause)` is created
- **THEN** `.manufacturer == "Mini-Circuits"`, `.context == "HTTP 503"`, `.cause is cause`
- **AND** `str(...)` contains both "Mini-Circuits" and "HTTP 503"

#### Scenario: Cause is included when present and omitted when absent

- **WHEN** the error has a cause `RuntimeError("boom")`
- **THEN** `"boom"` appears in `str(...)`
- **AND WHEN** the error is created with `cause=None`, `str(...)` still returns a non-empty message without raising

### Requirement: Mini-Circuits adapter retrieval

The Mini-Circuits adapter SHALL declare `manufacturer = "Mini-Circuits"` and support the `amplifier` component. On `search`, it SHALL issue a single HTTP GET to the amplifiers web page using a browser-style User-Agent, enforcing a minimum inter-request delay of at least 1 second between consecutive live fetches. IF the HTTP request fails, it SHALL raise `AdapterError` carrying the manufacturer and a context describing the fetch error. The adapter SHALL NOT apply any server-side parameter filtering: it returns all table rows as candidates and leaves all constraint checking to the Verifier.

#### Scenario: HTTP failure surfaces as AdapterError

- **WHEN** the live GET to the amplifiers page raises an HTTP error
- **THEN** the adapter raises an `AdapterError` whose manufacturer is `"Mini-Circuits"` and whose context describes the failed fetch

#### Scenario: All rows are returned for verification

- **WHEN** `search` succeeds
- **THEN** every parsed table row is returned as a `Candidate` without server-side filtering by frequency or any other parameter

### Requirement: Mini-Circuits results-table parsing

The adapter SHALL parse the results table identified by `table#maintable`; IF that table is absent it SHALL raise `AdapterError`. Column headers SHALL be matched by a normalized-header lookup against a fixed column map (`Model Number`, `F Low (MHz)`, `F High (MHz)`, `Gain`, `NF`, `P1dB`, `PSAT`→`Psat`, `OIP3`→`IP3`, `Voltage (V)`→`VDD`). The single-value `Voltage (V)` cell SHALL be stored as a degenerate range `RawValue((v, v), "V")` so `VDD` is a range everywhere (consistent with the other adapters). The `F Low`/`F High` MHz columns SHALL be combined into a single `freq_range` value `RawValue((low, high), "MHz")`, and only when both bounds are present. A `"DC"` low-band edge SHALL parse as `0.0`. Cells that are empty or a missing-value sentinel (`-`, `n/a`, `N/A`) SHALL cause the parameter to be absent from `raw_params` (not stored as `None`). A cell whose value cannot be parsed as a number — and is neither the `"DC"` low edge nor a known sentinel (e.g. a dual-range string such as `"350/480"`) — SHALL likewise cause the parameter to be absent from `raw_params`. Each parsed row SHALL produce `Candidate(model, manufacturer="Mini-Circuits", url, raw_params, source="table")`.

#### Scenario: Fixture parses into candidates with table source

- **WHEN** the saved amplifiers fixture is parsed
- **THEN** at least 10 candidates are returned
- **AND** each has `manufacturer == "Mini-Circuits"`, `source == "table"`, and a non-empty `model`

#### Scenario: Frequency range combined from two MHz columns

- **WHEN** the row for `ADCA3270` is parsed
- **THEN** its `raw_params["freq_range"] == RawValue((45.0, 1218.0), "MHz")`
- **AND** its `raw_params["Gain"] == RawValue(25.0, "dB")`

#### Scenario: Missing scalar parameters are absent, not None

- **WHEN** the row for `ADCA3270` (whose P1dB/PSAT/OIP3 cells are `-`) is parsed
- **THEN** `P1dB`, `Psat`, and `IP3` are absent from `raw_params`

#### Scenario: DC low edge becomes zero

- **WHEN** the row for `GALI-39+` (DC–8000 MHz) is parsed
- **THEN** its `raw_params["freq_range"] == RawValue((0.0, 8000.0), "MHz")`

#### Scenario: Voltage column maps to a degenerate VDD range

- **WHEN** a row whose `Voltage (V)` cell holds a single value (e.g. `24`) is parsed
- **THEN** its `raw_params["VDD"] == RawValue((24.0, 24.0), "V")`

#### Scenario: Unparseable cell yields an absent parameter

- **WHEN** a mapped parameter cell holds a value that is not numeric, not `"DC"`, and not a known sentinel (e.g. `"350/480"`)
- **THEN** parsing does not raise
- **AND** that parameter is absent from the candidate's `raw_params`

#### Scenario: Missing results table raises AdapterError

- **WHEN** `_parse_html("<html><body>no table here</body></html>")` is called
- **THEN** an `AdapterError` is raised

### Requirement: Candidate URL is populated for display only

Each `Candidate.url` SHALL be derived from the row's product link (`<a href>`), or fall back to a `modelSearch.html?model=<name>` URL, and SHALL contain the model name and the `minicircuits.com` host. The robots-disallowed `modelSearch.html` path SHALL be populated for human/report use only and SHALL never be fetched programmatically.

#### Scenario: URL identifies the model on the manufacturer host

- **WHEN** a candidate is parsed from the fixture
- **THEN** its `url` contains the candidate's `model` and the string `minicircuits.com`

### Requirement: Analog Devices adapter retrieval

The Analog Devices adapter SHALL declare `manufacturer = "Analog Devices"` and support the `amplifier` component. On `search`, it SHALL issue a single HTTP GET to the RF-amplifiers parametric JSON endpoint (catId `3003`) using a browser-style User-Agent, enforcing a minimum inter-request delay of at least 5 seconds between consecutive live fetches. IF the HTTP request fails, IF the response body is not valid JSON, or IF the parsed document has no `data` array, it SHALL raise `AdapterError` carrying the manufacturer and a context describing the failure. The adapter SHALL apply no server-side filtering: every row carrying a model becomes a `Candidate` and all constraint checking is left to the Verifier. Field ids SHALL be mapped to canonical parameters (`0`→model, `279`/`278`→`freq_range` low/high in `Hz`, `2930`→`P1dB`, `2922`→`IP3`, `2913`→`Gain`, `2921`→`NF`, `4709`→`Psat`); the `freq_range` value SHALL be built only when both frequency bounds are present; empty, sentinel (`-`, `n/a`, `N/A`, `NA`), or non-numeric cells SHALL cause that parameter to be absent from `raw_params`. Each `Candidate.url` SHALL be the `analog.com` product page for the lowercased model, and `source` SHALL be `table`.

#### Scenario: Parametric JSON parses into candidates

- **WHEN** the saved RF-amplifiers fixture is parsed
- **THEN** each candidate has `manufacturer == "Analog Devices"`, `source == "table"`, and a non-empty `model`
- **AND** a fully populated row exposes `freq_range`, `Gain`, `NF`, `P1dB`, `Psat`, and `IP3` in `raw_params`

#### Scenario: Frequency bounds combined in Hz with a zero low edge

- **WHEN** a DC-coupled row (`freq_low = 0`) is parsed
- **THEN** its `raw_params["freq_range"]` is `RawValue((0.0, high), "Hz")`
- **AND WHEN** the `freq_low` cell is empty, no `freq_range` is built

#### Scenario: Missing or unparseable cells drop the parameter

- **WHEN** a mapped cell is empty, a known sentinel, or non-numeric
- **THEN** that parameter is absent from the candidate's `raw_params`

#### Scenario: Bad payloads surface as AdapterError

- **WHEN** `_parse_json` receives a body that is not valid JSON, or a JSON document without a `data` array
- **THEN** an `AdapterError` is raised

#### Scenario: Row without a model is skipped

- **WHEN** a data row has no model field (`0`)
- **THEN** it produces no candidate

### Requirement: Qorvo adapter retrieval and parsing

The Qorvo adapter SHALL declare `manufacturer = "Qorvo"` and support the `amplifier` component. On `search`, it SHALL issue a single HTTP GET to the server-rendered product list at `/products/product-list/` (no query string) using a browser-style User-Agent; IF the fetch fails or the product container is absent it SHALL raise `AdapterError` carrying the manufacturer. The adapter SHALL keep only the 12 amplifier categories (by `h3` title) and drop all other category blocks. Columns SHALL be mapped by header title with the unit read per-column from the header subtitle (`Frequency Min`/`Max` in GHz or MHz, `Gain`, `OP1dB`→`P1dB`, `OIP3`→`IP3`, `NF`, `Psat`, `Voltage`/`Vd`→`VDD`); `Vg` (gate) SHALL be ignored. A `Frequency Min` of `"DC"` SHALL parse as `0.0`. A `VDD` cell SHALL parse as a `"X to Y"` range, a single value stored as `(v, v)`, or a comma/slash multi-value list stored as a discrete option list. For Spatium parts, `Small Signal Gain` SHALL map to `Gain`. `Size`, `MSL`, and `Temperature` SHALL never be emitted (listing-page only). Empty or `"N/A"` cells SHALL cause the parameter to be absent. Each row SHALL produce `Candidate(model, manufacturer="Qorvo", url=/products/p/{MODEL}, raw_params, source="table")`.

#### Scenario: Only amplifier categories are kept

- **WHEN** the saved product-list fixture is parsed
- **THEN** only parts from the 12 amplifier categories are returned

#### Scenario: DC frequency low edge becomes zero

- **WHEN** a row whose `Frequency Min` is `"DC"` is parsed
- **THEN** its `freq_range` low edge is `0.0`

#### Scenario: VDD parses as range, single value, or discrete list

- **WHEN** a `VDD` cell holds `"3 to 5"`, a single value, or `"3, 5, 8"`
- **THEN** it is stored as a `(low, high)` range, a `(v, v)` range, or a discrete option list respectively

#### Scenario: Spatium uses small-signal gain

- **WHEN** a Spatium part with both `Small Signal Gain` and `Power Gain` is parsed
- **THEN** `Gain` is taken from `Small Signal Gain`

#### Scenario: Size, MSL, Temperature never emitted

- **WHEN** any Qorvo row is parsed
- **THEN** `Size`, `MSL`, and `Temperature` are absent from `raw_params`

#### Scenario: Missing container raises AdapterError

- **WHEN** the product container is absent from the HTML
- **THEN** an `AdapterError` is raised

### Requirement: VectraWave adapter retrieval and parsing

The VectraWave adapter SHALL declare `manufacturer = "VectraWave"` and support the `amplifier` component. On `search`, it SHALL issue a single HTTP GET to the server-rendered `/search-engine-mmic` page; IF the fetch fails or the expected modules are absent it SHALL raise `AdapterError`. The page tables are **transposed** (each product is a column, each parameter a row); the adapter SHALL parse only the four amplifier sections (High Power, Medium Power, Low Noise, Wideband) and SHALL skip attenuators, phase shifters, and Core Chips (the dual-path T/R modules are deferred — see open question OQ-5). It SHALL map `FrequencyMin`/`Max` (GHz) to `freq_range`, `Pout`→`Psat`, `OP1dB`→`P1dB`, `Gain`, `NF`, and both supply-voltage labels → `VDD` (dual-rail supported); a control-voltage label SHALL NOT map to `VDD`. `IP3`, `MSL`, `Size`, and `Temperature` SHALL NOT be emitted from the table (not published by VectraWave / datasheet-only). Each row SHALL produce `Candidate(model, manufacturer="VectraWave", url=<datasheet PDF or page>, raw_params, source="table")`.

#### Scenario: Only amplifier sections are returned

- **WHEN** the saved MMIC fixture is parsed
- **THEN** only parts from the four amplifier sections (High Power, Medium Power, Low Noise, Wideband) are returned
- **AND** attenuators, phase shifters, and Core Chips are excluded

#### Scenario: Transposed products are parsed

- **WHEN** the transposed table is parsed
- **THEN** each product column becomes a candidate with its per-row parameters

#### Scenario: Pout maps to Psat, not P1dB

- **WHEN** a power-amp row exposes `Pout`
- **THEN** it is stored under `Psat`

#### Scenario: Control voltage is not VDD

- **WHEN** a control-voltage label is present
- **THEN** it is not mapped to `VDD`

#### Scenario: IP3/MSL/Size/Temperature absent from table

- **WHEN** any VectraWave row is parsed
- **THEN** `IP3`, `MSL`, `Size`, and `Temperature` are absent from `raw_params`

#### Scenario: Missing modules raise AdapterError

- **WHEN** the expected modules are absent
- **THEN** an `AdapterError` is raised

### Requirement: Guerrilla RF adapter retrieval and parsing

The Guerrilla RF adapter SHALL declare `manufacturer = "Guerrilla RF"` and support the `amplifier` component. On `search`, it SHALL issue a single HTTP GET to the server-rendered `/products/amplifiers.html` page and parse both tables (`#genericAmpFunctionTbl` and `#satPATbl`); IF the fetch fails or the tables are absent it SHALL raise `AdapterError`. `Min`/`Max Freq` (GHz) SHALL combine into `freq_range` (a DC-coupled low edge → `0.0`); `Gain`, `NF`, `OP1dB`→`P1dB`, `OIP3`→`IP3`, `Psat`, and `Vdd Range (V)`→`VDD` (a `"low-high"` string) SHALL be mapped. An empty `""` cell SHALL cause the parameter to be absent (including an empty `VDD`). `MSL`, `Temperature`, and exact `Size` SHALL NOT be emitted (datasheet-only). Each row SHALL produce `Candidate(model, manufacturer="Guerrilla RF", url, raw_params, source="table")`.

#### Scenario: Both tables are parsed

- **WHEN** the saved amplifiers fixture is parsed
- **THEN** candidates come from both `#genericAmpFunctionTbl` and `#satPATbl`

#### Scenario: DC-coupled low edge becomes zero

- **WHEN** a DC-coupled row is parsed
- **THEN** its `freq_range` low edge is `0.0`

#### Scenario: Vdd Range parses to a VDD range

- **WHEN** a `Vdd Range (V)` cell holds `"low-high"`
- **THEN** it is stored under `VDD` as a `(low, high)` range

#### Scenario: Empty cells are absent

- **WHEN** a scalar or `VDD` cell is empty
- **THEN** that parameter is absent from `raw_params`

#### Scenario: Missing tables raise AdapterError

- **WHEN** both tables are absent
- **THEN** an `AdapterError` is raised
