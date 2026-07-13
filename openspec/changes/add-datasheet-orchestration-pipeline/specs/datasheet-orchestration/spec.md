## ADDED Requirements

### Requirement: A management layer owns and coordinates the search flow

The system SHALL provide a dedicated management (orchestration) layer that is the single owner of the end-to-end search flow. This layer, and only this layer, SHALL drive the other layers: it selects the adapters that support the requested component type and calls them to retrieve candidates, it calls `verifier.verify()` to obtain verdicts, and it calls the datasheet layer to enrich candidates. The adapter, verifier, and datasheet layers SHALL remain independent building blocks that do not call one another; the management layer wires them together and enforces the two-gate policy. It SHALL expose a single entry point (e.g. `run_pipeline(spec, *, on_source=None) -> list[VerifiedCandidate]`) that the CLI and GUI front-ends call instead of driving the stages themselves.

#### Scenario: The management layer drives every stage

- **WHEN** a front-end (CLI or GUI) requests a search for a `QuerySpec`
- **THEN** it calls the management layer's single entry point
- **AND** the management layer — not the front-end and not the individual layers — selects and calls the adapters, calls `verify()`, and calls the datasheet layer, in that order

#### Scenario: Layers stay decoupled

- **WHEN** the pipeline runs
- **THEN** the adapter layer does not call the verifier or the datasheet layer, and the verifier does not call the datasheet layer
- **AND** all coordination between them happens in the management layer

### Requirement: Two-gate gated pipeline

The management layer SHALL sequence four stages in order: (1) each supporting adapter retrieves every component it lists for the requested component type, (2) a table-based Gate 1, (3) datasheet enrichment of Gate 1 survivors, (4) a final Gate 2. The pipeline SHALL reuse `verifier.verify()` as the only comparison engine; each gate SHALL be a policy over the verdicts `verify()` produces, not a second comparator. The pipeline SHALL return only the candidates that pass Gate 2 (each carrying the component's link).

#### Scenario: Stages run in order and reuse verify

- **WHEN** the pipeline runs for a `QuerySpec`
- **THEN** it first retrieves table candidates, then applies Gate 1, then enriches survivors from datasheets, then applies Gate 2
- **AND** every PASS/FAIL/UNKNOWN decision is produced by `verifier.verify()`, not a separate comparator

#### Scenario: One failing source does not abort the pipeline

- **WHEN** one adapter raises during retrieval, or one candidate's datasheet fetch or extraction fails
- **THEN** that source/candidate is skipped and the remaining candidates are processed to completion

### Requirement: Gate 1 keeps only candidates whose table parameters all pass

Gate 1 SHALL run `verify()` on each retrieved candidate and SHALL let a candidate advance to enrichment ONLY when every requested parameter the adapter provides from the site table verifies as `PASS`. A requested parameter that does not appear on the site (verdict `UNKNOWN`) SHALL NOT block a candidate at Gate 1 — it is deferred to the datasheet stage. A candidate for which any table-provided parameter `FAIL`s SHALL be dropped and SHALL NOT be enriched. Gate 1 SHALL NOT fetch any datasheet.

#### Scenario: All table-provided parameters pass, some unknown

- **WHEN** a candidate's table values for the requested parameters are all `PASS`, and other requested parameters are `UNKNOWN` (absent from the site)
- **THEN** Gate 1 advances the candidate to the datasheet enrichment stage

#### Scenario: A table-provided parameter fails

- **WHEN** any requested parameter the table provides yields a `FAIL` verdict
- **THEN** Gate 1 drops the candidate and it is not enriched

### Requirement: Datasheet enrichment of the parameters missing from the site

For each Gate 1 survivor, the enrichment stage SHALL determine the requested parameters that do not appear on the site (verdict `UNKNOWN`) and SHALL resolve those, and only those, from the candidate's datasheet. When the candidate has a `datasheet_url`, the stage SHALL fetch the datasheet PDF, extract its text, run the existing LLM extractor requesting ONLY the missing parameter names, map the result to `RawValue` via the existing datasheet mapping, and merge the newly resolved values into a copy of the candidate. Merged values SHALL carry `source="datasheet"`; the candidate's original table values SHALL NOT be overwritten. A survivor whose requested parameters are already all `PASS` (nothing missing) SHALL skip enrichment entirely.

#### Scenario: Only the site-missing parameters are requested from the datasheet

- **WHEN** a survivor passes `freq_range` from the table but leaves `Temperature` and `MSL` `UNKNOWN` (absent from the site)
- **THEN** the extractor is asked for `Temperature` and `MSL` only, not for `freq_range`

#### Scenario: Resolved datasheet values are merged as datasheet source

- **WHEN** the datasheet yields a value for a parameter that was missing from the site
- **THEN** that value is added to the candidate's `raw_params` with `source="datasheet"`
- **AND** the candidate's existing table values are left unchanged

#### Scenario: Survivor with nothing missing skips enrichment

- **WHEN** a survivor already has every requested parameter as `PASS` from the table
- **THEN** no datasheet is fetched for it

### Requirement: Enrichment requires a datasheet URL

Datasheet enrichment SHALL run only for candidates that carry a non-empty `datasheet_url`. A survivor without a `datasheet_url` and with at least one site-missing parameter SHALL be left unchanged (its `UNKNOWN` parameters stay `UNKNOWN`) and SHALL therefore be dropped by Gate 2.

#### Scenario: Candidate without a datasheet URL is not enriched

- **WHEN** a Gate 1 survivor has `datasheet_url` unset and at least one site-missing parameter
- **THEN** no datasheet fetch is attempted for it
- **AND** it is dropped by Gate 2

### Requirement: Gate 2 returns a candidate only when the datasheet parameters also all pass

After enrichment, Gate 2 SHALL re-verify each candidate and SHALL return a candidate ONLY when every requested parameter — those already passing from the table AND those resolved from the datasheet — verifies as `PASS` (overall outcome `match`). If any datasheet-resolved parameter `FAIL`s, or any requested parameter remains `UNKNOWN` after enrichment, the candidate SHALL be dropped and SHALL NOT appear in the result.

#### Scenario: Datasheet parameters all pass

- **WHEN** every parameter resolved from the datasheet verifies as `PASS` and no table parameter failed
- **THEN** the candidate's Gate 2 outcome is `match` and it is returned (with its link)

#### Scenario: A datasheet parameter fails the requirement

- **WHEN** a parameter resolved from the datasheet `FAIL`s the requirement
- **THEN** the candidate is dropped and does not appear in the result

#### Scenario: A requested parameter stays unresolved

- **WHEN** a requested parameter is on neither the site nor the datasheet (no `datasheet_url`, the fetch failed, or the datasheet does not state it) and stays `UNKNOWN`
- **THEN** the candidate is dropped and does not appear in the result

### Requirement: Fetch a datasheet PDF from a URL

The datasheet layer SHALL provide the ability to obtain datasheet text from a PDF URL, not only from a local file path: download the PDF from the URL and produce the same text output the existing local-file extractor produces. A fetch that fails (network error, non-PDF response, or HTTP error) SHALL raise a well-defined error the pipeline can catch and treat as "not enriched", rather than aborting the run.

#### Scenario: Datasheet text is produced from a URL

- **WHEN** enrichment is given a candidate's `datasheet_url`
- **THEN** the PDF is downloaded and its text is extracted for the LLM extractor

#### Scenario: A failed fetch is contained

- **WHEN** downloading or parsing a candidate's datasheet PDF fails
- **THEN** the error is caught, the candidate is left unenriched, and the rest of the pipeline continues

### Requirement: Datasheet extraction is cached

To avoid re-downloading and re-running the LLM for the same work, the enrichment stage SHALL cache datasheet extraction so that a repeated request for the same datasheet source and the same requested-parameter set within a run reuses the prior result instead of fetching and extracting again.

#### Scenario: Repeated datasheet work is served from cache

- **WHEN** two candidates share the same `datasheet_url` and require the same missing parameters, or the same candidate is enriched twice in a run
- **THEN** the PDF is fetched and the extractor is invoked at most once for that (datasheet, parameters) pair
