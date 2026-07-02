# Manufacturer Adapters Specification

## Purpose

Define the pluggable adapter layer that retrieves candidate components from a manufacturer source and maps them into the tool's canonical model. Adapters only fetch and map raw values; they never judge whether a candidate matches (that is the Verifier's job). This spec documents the behavior **as currently implemented** in `rf_finder/adapters/base.py`, `rf_finder/adapters/minicircuits.py`, `rf_finder/adapters/analogdevices.py`, `rf_finder/adapters/amcomusa.py`, `rf_finder/adapters/marki.py`, and `rf_finder/adapters/rwmmic.py`.

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

The adapter SHALL parse the results table identified by `table#maintable`; IF that table is absent it SHALL raise `AdapterError`. Column headers SHALL be matched by a normalized-header lookup against a fixed column map (`Model Number`, `F Low (MHz)`, `F High (MHz)`, `Gain`, `NF`, `P1dB`, `PSAT`→`Psat`, `OIP3`→`IP3`). The `F Low`/`F High` MHz columns SHALL be combined into a single `freq_range` value `RawValue((low, high), "MHz")`, and only when both bounds are present. A `"DC"` low-band edge SHALL parse as `0.0`. Cells that are empty or a missing-value sentinel (`-`, `n/a`, `N/A`) SHALL cause the parameter to be absent from `raw_params` (not stored as `None`). A cell whose value cannot be parsed as a number — and is neither the `"DC"` low edge nor a known sentinel (e.g. a dual-range string such as `"350/480"`) — SHALL likewise cause the parameter to be absent from `raw_params`. Each parsed row SHALL produce `Candidate(model, manufacturer="Mini-Circuits", url, raw_params, source="table")`.

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

### Requirement: AmcomUSA adapter retrieval

The AmcomUSA adapter SHALL declare `manufacturer = "AmcomUSA"` and support the `amplifier` component. On `search`, it SHALL issue one HTTP GET per amplifier **category page** using a browser-style User-Agent, enforcing a minimum inter-request delay of at least 1.5 seconds and retrying transient failures up to 3 times before raising. Each category SHALL be fetched independently: a page that fails or has no product table SHALL be skipped, and `AdapterError` SHALL be raised only when **every** category fetch fails. The adapter SHALL apply no server-side filtering and return all rows for the Verifier.

The adapter SHALL parse the table `table#allPnTable`, reading the **last** `<thead>` row as the column headers and taking each data value from the **cell text** (a `ddtf-value` attribute is preferred only when present). Columns SHALL be mapped by normalized header name: `Fmin`/`Fmax` combine into `freq_range` with the unit taken from the header (`MHz` or `GHz`); `Gain`→`Gain` (dB); `NF`→`NF` (dB); `P1dB`→`P1dB` (dBm); `Pout` or `Psat`→`Psat` (dBm); `OIP3`→`IP3` (dBm); `Vd` or `Bias`→`VDD` (V). A cell that is empty, a missing sentinel (`-`, `n/a`, `N/A`, `TBD`), or not a single float (e.g. a dual-supply string such as `"+8 / -0.75"`) SHALL cause that parameter to be absent from `raw_params`. The card-only "Rackmount HPAs" category SHALL yield candidates carrying only a model and URL (empty `raw_params`). Each parsed row SHALL produce `Candidate(model, manufacturer="AmcomUSA", url, raw_params, source="table")`.

#### Scenario: Scalar and frequency columns map to canonical params

- **WHEN** a category row with `Fmin`/`Fmax (GHz)`, `Gain (dB)`, and `P1dB (dBm)` cells is parsed
- **THEN** `raw_params["freq_range"]` is the `(low, high)` GHz tuple
- **AND** `Gain` and `P1dB` are present with their canonical units

#### Scenario: Missing cell yields an absent parameter

- **WHEN** a mapped cell holds `-`
- **THEN** that parameter is absent from `raw_params`

#### Scenario: Either supply-voltage header maps to VDD

- **WHEN** a row has a `Vd (V)` column, **or** a `Bias (V)` column
- **THEN** `raw_params["VDD"]` is present with unit `V`

#### Scenario: Dual-supply string is not a single VDD

- **WHEN** a supply cell holds `"+8 / -0.75"`
- **THEN** `VDD` is absent from `raw_params`

### Requirement: Marki Microwave adapter retrieval

The Marki adapter SHALL declare `manufacturer = "Marki Microwave"` and support the `amplifier` component. On `search`, it SHALL fetch the SvelteKit-rendered search results with paginated HTTP GETs to `/search/?item_per_page=…&page=…&keyword=&family=amplifiers` using a browser-style User-Agent, a minimum inter-request delay of at least 1.5 seconds, and up to 3 retries. It SHALL apply no server-side filtering and return all rows.

In each results row the part number is a leading `<th>` whose `<a>` supplies the model text and the product URL, and the data `<td>` cells align to the header list **after** the part-number column. Columns SHALL be mapped by normalized header name (square brackets stripped): `F Low`/`F High [GHz]` combine into `freq_range` (GHz); `Gain`→`Gain` (dB); `NF`→`NF` (dB); `Psat`→`Psat` (dBm); `OIP3`→`IP3` (dBm); `P1dB`→`P1dB` (dBm). A `-` or empty cell SHALL cause the parameter to be absent; an `F Low` of `0` SHALL parse as `0.0`. Each row SHALL produce `Candidate(model, manufacturer="Marki Microwave", url, raw_params, source="table")` with `url` set to the product page.

Only when the query constrains `Size`, `VDD`, or `Temperature` SHALL the adapter perform a second per-product page fetch to enrich those params: `Size` from the product-table row whose part number equals the model (the larger dimension, in `mm`; the EVB variant's `-` is ignored), `VDD` from the `power_supply_voltage` value in the page's JS payload (`V`), and `Temperature` from the payload's `temperature` value stored as a degenerate `(t, t)` range (`degC`). A per-page failure SHALL leave those params UNKNOWN. `MSL` SHALL always be left UNKNOWN (available only in datasheet PDFs, which are not fetched).

#### Scenario: Leading part-number th does not shift column mapping

- **WHEN** a results row is parsed
- **THEN** `Gain`, `NF`, `IP3`, and `P1dB` take their values from the correct columns (the `<td>` cells align to the headers after "Part Number")

#### Scenario: Frequency range is a GHz tuple

- **WHEN** a row with `F Low`/`F High [GHz]` is parsed
- **THEN** `raw_params["freq_range"]` is `RawValue((low, high), "GHz")`

#### Scenario: DC-coupled low edge becomes zero

- **WHEN** a bare-die row lists `F Low = 0`
- **THEN** its `freq_range` low bound is `0.0` and the row is kept

#### Scenario: Size taken from the matching variant row

- **WHEN** the product page is enriched for a model whose row lists `"4 x 4 mm"` while the EVB variant lists `-`
- **THEN** `raw_params["Size"]` is the larger dimension in `mm`
- **AND** the EVB variant does not set `Size`

#### Scenario: VDD and Temperature from the JS payload

- **WHEN** the product page carries `power_supply_voltage:[{value:"5"}]` and `temperature:"25"`
- **THEN** `raw_params["VDD"] == RawValue(5.0, "V")`
- **AND** `raw_params["Temperature"] == RawValue((25.0, 25.0), "degC")`

#### Scenario: Product-page enrichment only when required

- **WHEN** the query constrains none of `Size`, `VDD`, or `Temperature`
- **THEN** no per-product page is fetched

### Requirement: RWM adapter retrieval

The RWM adapter SHALL declare `manufacturer = "RWM"` and support the `amplifier` component. On `search`, it SHALL issue a single HTTP GET to the site's JSON product API `index.php?r=api/all-products` using a browser-style User-Agent and a minimum inter-request delay of at least 1 second; because the host serves a self-signed certificate in its chain, TLS verification SHALL be disabled for this request. IF the response body is not valid JSON, or IF it has no `data` array of category groups, it SHALL raise `AdapterError`. It SHALL apply no server-side filtering and return all amplifier rows.

The adapter SHALL select category groups whose category name contains "Amplifier" and map each product's `field_values` by field name: `Freq Low`/`Freq High (GHz)` combine into `freq_range` (GHz, `"DC"`→`0.0`); `NF`→`NF` (dB); `P1dB`→`P1dB` (dBm); `Psat`→`Psat` (dBm); `Voltage` or `Vd (V)`→`VDD` (V). Canonical `Gain` SHALL be taken **only** from a field whose exact label is `"Gain (dB)"` — `"Small Signal Gain (dB)"` and `"Power Gain (dB)"` SHALL NOT be treated as `Gain`. IP3/OIP3 is not published and SHALL be absent. Each `Candidate.url` SHALL be the per-part datasheet link (populated for display only) and `source` SHALL be `table`.

A product characterised at several coupled operating points publishes `/`-separated per-point values aligned by position across fields; the adapter SHALL emit one `Candidate` per operating point (model labelled `"PN (op i/N)"`), assigning each field its i-th value while sharing single-valued fields across all points. IF the multi-valued fields disagree on their count, the adapter SHALL emit a single candidate with those multi-valued fields left absent.

#### Scenario: Only amplifier categories are returned

- **WHEN** the catalogue is parsed
- **THEN** products from non-amplifier categories (e.g. switches) produce no candidates

#### Scenario: Gain only from the exact "Gain (dB)" field

- **WHEN** a product exposes a field labelled exactly `"Gain (dB)"`
- **THEN** `raw_params["Gain"]` is set from it
- **AND WHEN** a product exposes only `"Small Signal Gain (dB)"` / `"Power Gain (dB)"`, `Gain` is absent

#### Scenario: Coupled operating points expand into separate candidates

- **WHEN** a product lists `Gain "24/23.5"`, `P1dB "27/29"`, and `Voltage "5/6"`
- **THEN** two candidates are produced — `"… (op 1/2)"` with `Gain 24 / P1dB 27 / VDD 5` and `"… (op 2/2)"` with `Gain 23.5 / P1dB 29 / VDD 6`
- **AND** single-valued fields (e.g. the frequency band) are shared across both

#### Scenario: Mismatched value counts fall back safely

- **WHEN** a product's multi-valued fields disagree on their count
- **THEN** a single candidate is produced with those multi-valued fields absent

#### Scenario: Candidate URL is the datasheet link

- **WHEN** a candidate is produced
- **THEN** its `url` is the product's datasheet link on the `rwmmic.com` host

#### Scenario: Bad payloads surface as AdapterError

- **WHEN** `_parse_json` receives a body that is not valid JSON, or a document without a `data` array
- **THEN** an `AdapterError` is raised
