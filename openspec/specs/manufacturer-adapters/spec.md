# Manufacturer Adapters Specification

## Purpose

Define the pluggable adapter layer that retrieves candidate components from a manufacturer source and maps them into the tool's canonical model. Adapters only fetch and map raw values; they never judge whether a candidate matches (that is the Verifier's job). This spec documents the behavior **as currently implemented** in `rf_finder/adapters/base.py`, `rf_finder/adapters/minicircuits.py`, `rf_finder/adapters/analogdevices.py`, `rf_finder/adapters/amcomusa.py`, `rf_finder/adapters/marki.py`, `rf_finder/adapters/rwmmic.py`, `rf_finder/adapters/macom.py`, `rf_finder/adapters/ums.py`, `rf_finder/adapters/threerwave.py`, `rf_finder/adapters/microchip.py`, `rf_finder/adapters/qorvo.py`, `rf_finder/adapters/vectrawave.py`, and `rf_finder/adapters/guerrillarf.py`.

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

### Requirement: MACOM adapter retrieval

The MACOM adapter SHALL declare `manufacturer = "MACOM"` and support the `amplifier` component. On `search`, it SHALL issue a single HTTP GET to the all-amplifiers page (`https://www.macom.com/products/rf-microwave-mmwave/amplifiers/all-amplifiers`) using a browser-style User-Agent, enforcing a minimum inter-request delay of at least 60 seconds between consecutive live fetches. The numeric specs SHALL be read from each product row's HTML-entity-encoded `data-part` JSON attribute (not from rendered table cells): every `data-part` blob SHALL be regex-extracted, HTML-unescaped, and parsed with `json.loads(..., strict=False)`, and a blob that fails to parse SHALL be skipped rather than aborting the run. IF the HTTP request fails it SHALL raise `AdapterError` carrying the manufacturer and a context describing the failed fetch; IF no `data-part` rows are found it SHALL raise `AdapterError`. Each `specName` SHALL be normalized (lowercased, whitespace-collapsed) and mapped to canonical parameters (`gain`→`Gain` dB, `output p1db`→`P1dB` dBm, `oip3`→`IP3` dBm, `nf`/`noise figure`→`NF` dB, `psat`→`Psat` dBm); `Min Frequency` + `Max Frequency` SHALL be combined into `freq_range` as `RawValue((low, high), "MHz")` only when both bounds are present; empty or non-numeric specs SHALL cause that parameter to be absent from `raw_params`. The adapter SHALL apply no server-side filtering: every part carrying a `partNumber` becomes `Candidate(model, manufacturer="MACOM", url, raw_params, source="table")` where `url` is the `macom.com` product-detail page; a part without a `partNumber` is skipped.

#### Scenario: data-part JSON parses into candidates

- **WHEN** the saved all-amplifiers fixture is parsed
- **THEN** each candidate has `manufacturer == "MACOM"`, `source == "table"`, and a non-empty `model`

#### Scenario: Noise Figure synonym maps to NF

- **WHEN** a part's specs use the `Noise Figure` name rather than `NF`
- **THEN** its value is stored under `raw_params["NF"]`

#### Scenario: Missing spec is absent, not None

- **WHEN** a part omits `P1dB`/`IP3`/`NF` specs
- **THEN** those parameters are absent from the candidate's `raw_params`

#### Scenario: No data-part rows raises AdapterError

- **WHEN** the HTML contains no `data-part` product rows
- **THEN** an `AdapterError` is raised

### Requirement: UMS adapter retrieval

The UMS adapter SHALL declare `manufacturer = "UMS"` and support the `amplifier` component. On `search`, it SHALL issue one HTTP GET per amplifier sub-type slug (`amplifier-lna`, `amplifier-hpa`, `amplifier-mpa`, `amplifier-analogvga`, `amplifier-digitalvga`) to the parametric `?function=<slug>` URL, always sending the full default frequency/power range (the site's server-side numeric filter is broken and narrowing it returns zero rows), using a browser-style User-Agent and enforcing a minimum inter-request delay of at least 3 seconds between consecutive live fetches. IF an HTTP request fails, IF no product table is found, or IF the table has no `<thead>` column labels, it SHALL raise `AdapterError`. The parametric table SHALL be located via its `tr.product-row` rows; header labels SHALL be read nested-tolerantly and mapped by **normalized label** (not by column position): `gain db`→`Gain` dB, `noise figure db`→`NF` dB, `p 1db out dbm`→`P1dB` dBm, `ip3 dbm`→`IP3` dBm, `sat output power dbm`→`Psat` dBm, `bias v`→`VDD` V; the `rf bandwidth ghz` min and max headers SHALL be combined into `freq_range` as `RawValue((low, high), "GHz")`. Empty, dash, or sentinel cells SHALL cause that parameter to be absent from `raw_params`. The adapter SHALL apply no server-side filtering: each row becomes `Candidate(model, manufacturer="UMS", url, raw_params, source="table")` where `model` comes from the `a.product-link` text and `url` is that link (or a `/products/<model>/` fallback).

#### Scenario: Per-category columns are mapped by label

- **WHEN** an LNA table (with a Noise Figure column and no IP3) and an HPA table (with IP3 and Sat. Output Power columns and no NF) are parsed
- **THEN** LNA candidates expose `NF` and not `IP3`, and HPA candidates expose `IP3`/`Psat` and not `NF`

#### Scenario: Frequency range combined in GHz

- **WHEN** a row's RF Bandwidth min/max cells are parsed
- **THEN** its `raw_params["freq_range"]` is `RawValue((low, high), "GHz")`

#### Scenario: Empty or dash cell drops the parameter

- **WHEN** a mapped cell is empty, `-`, or a known sentinel
- **THEN** that parameter is absent from the candidate's `raw_params`

#### Scenario: Missing product table raises AdapterError

- **WHEN** the fetched HTML contains no parametric product table
- **THEN** an `AdapterError` is raised

### Requirement: 3rWave adapter retrieval

The 3rWave adapter SHALL declare `manufacturer = "3rWave"` and support the `amplifier` component (covering both the PA and LNA sub-types). On `search`, it SHALL issue a single HTTP GET to `https://3rwave.com/amplifier/` using a browser-style User-Agent, enforcing a minimum inter-request delay of at least 1 second between consecutive live fetches. It SHALL parse **all** `table.tablepress` tables on the page (never hard-coding a TablePress id), locate each table's header row by a cell that normalizes to `part number`, and build a normalized-header→column-index map with a positional fallback. Columns SHALL be mapped as: Start Freq. + Stop Freq. (GHz)→`freq_range` `RawValue((low, high), "GHz")`, `gain db`→`Gain` dB, `psat dbm`→`Psat` dBm, `nf db`→`NF` dB, `drain voltage v`→`VDD` V. `Size` and `P1dB`/`IP3`/`MSL`/`Temperature` SHALL NOT be populated by this adapter (deferred, or absent as a column). Rows without a Part Number, and empty or sentinel cells, SHALL be skipped or cause the parameter to be absent. IF the HTTP request fails, IF the response is intercepted by a content filter, or IF no `table.tablepress` is found, it SHALL raise `AdapterError`. The adapter SHALL apply no server-side filtering: each row becomes `Candidate(model, manufacturer="3rWave", url, raw_params, source="table")` where `url` is the per-part link or an amplifier-page fallback.

#### Scenario: PA and LNA rows parse into candidates

- **WHEN** the saved amplifier-page fixture (PA + LNA tables) is parsed
- **THEN** each candidate has `manufacturer == "3rWave"`, `source == "table"`, and a non-empty `model`

#### Scenario: Frequency range combined in GHz

- **WHEN** a row's Start Freq. and Stop Freq. (GHz) cells are parsed
- **THEN** its `raw_params["freq_range"]` is `RawValue((low, high), "GHz")`

#### Scenario: Size is not emitted

- **WHEN** any row is parsed
- **THEN** `Size` is absent from the candidate's `raw_params` (Size parsing is deferred)

#### Scenario: No tablepress table raises AdapterError

- **WHEN** the fetched HTML contains no `table.tablepress`
- **THEN** an `AdapterError` is raised

### Requirement: Microchip adapter retrieval (JSON API)

The Microchip adapter SHALL declare `manufacturer = "Microchip"` and support the `amplifier` component. On `search`, it SHALL source data entirely from the Microchip MCP server (`https://api.microchip.com/mcp/resources`) and the `microchipdirect.com` per-part JSON feeds, and SHALL NOT access `www.microchip.com`. Retrieval SHALL be a three-step chain: (1) MCP `tools/call` `search_products` over a union of amplifier search terms, paginated on `hasMore` and de-duplicated by part number; (2) per part, run concurrently in a bounded `ThreadPoolExecutor` (max 8 workers), MCP `search_product_physical_specs` to obtain the `parametricData` feed URL plus package size and MSL; (3) an HTTP GET of that feed for the electrical specs. MCP responses are SSE-framed JSON-RPC whose payload is double-encoded (parse the `data:` line → `result.content[0].text` → `json.loads`). Only feeds whose `product_type` marks an amplifier SHALL be kept (text-search pollution is dropped). Feed fields SHALL be mapped as: `Gain (dB)`→`Gain`, `NF (dB)`→`NF`, `OIP3 (dBm)`→`IP3`, `p1db(dBM)`→`P1dB`, `Pout (dBm)`→`Psat`; `Freq Min GHz`/`Freq Max GHz`→`freq_range` in GHz (`"DC"`→`0.0`); the `Bias` string→`VDD` (leading volts); `Size`→largest edge of `packageWidthOrSize`; `MSL`→the digit of `MSL-n`. Missing or non-numeric values SHALL cause the parameter to be absent. Per-part failures SHALL return `None` and be skipped; MCP transport or response-shape errors SHALL raise `AdapterError`; IF enumeration yields zero parts across all terms it SHALL raise `AdapterError`. The adapter SHALL apply no server-side filtering: each amplifier becomes `Candidate(model, manufacturer="Microchip", url, raw_params, source="table")` where `url` is the part's `productUrl`.

#### Scenario: Feed fixtures parse into candidates

- **WHEN** the saved feed fixtures are parsed
- **THEN** each candidate has `manufacturer == "Microchip"`, `source == "table"`, and a non-empty `model`

#### Scenario: product_type gate drops non-amplifiers

- **WHEN** a feed's `product_type` does not mark an amplifier (or is absent)
- **THEN** that part produces no candidate

#### Scenario: Bias string yields VDD in volts

- **WHEN** a feed's `Bias` is a compound string such as `"4V, 80mA"`
- **THEN** `raw_params["VDD"]` is the leading voltage in volts

#### Scenario: Zero enumerated parts raises AdapterError

- **WHEN** MCP `search_products` returns no parts for any amplifier term
- **THEN** an `AdapterError` is raised

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
