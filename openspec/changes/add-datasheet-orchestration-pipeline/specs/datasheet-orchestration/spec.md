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

The management layer SHALL sequence five stages in order: (1) each supporting adapter retrieves every component it lists for the requested component type, (2) a table-based Gate 1, (3) datasheet-link resolution for Gate 1 survivors, (4) datasheet enrichment of those survivors, (5) a final Gate 2. The pipeline SHALL reuse `verifier.verify()` as the only comparison engine; each gate SHALL be a policy over the verdicts `verify()` produces, not a second comparator. The **same `QuerySpec` (the user's requirements) SHALL be used at both gates** — the requirements never change between Gate 1 and Gate 2; only the candidate changes (Gate 2 sees the datasheet-enriched candidate). The pipeline SHALL return the candidates Gate 2 accepts — both **fully verified** candidates (result outcome `match`) and candidates whose site parameters all pass but whose datasheet could not be accessed to confirm the still-missing parameters (result outcome `not-verified`); candidates with any failing parameter SHALL be dropped. Each returned candidate carries the component's link and its result outcome.

#### Scenario: Stages run in order and reuse verify

- **WHEN** the pipeline runs for a `QuerySpec`
- **THEN** it first retrieves table candidates, then applies Gate 1, then resolves each survivor's datasheet link, then enriches survivors from datasheets, then applies Gate 2
- **AND** every PASS/FAIL/UNKNOWN decision is produced by `verifier.verify()`, not a separate comparator

#### Scenario: Both gates verify against the same user requirements

- **WHEN** Gate 1 verifies a candidate and Gate 2 re-verifies its enriched form
- **THEN** both calls pass the same `QuerySpec` (the user's constraints)
- **AND** only the candidate differs between the two calls — Gate 2's candidate additionally carries the datasheet-resolved values

#### Scenario: One failing source does not abort the pipeline

- **WHEN** one adapter raises during retrieval, or one candidate's datasheet fetch or extraction fails
- **THEN** that source/candidate is skipped and the remaining candidates are processed to completion

### Requirement: Gate 1 keeps only candidates whose table parameters all pass

Gate 1 SHALL run `verify()` on each retrieved candidate and SHALL let a candidate advance to enrichment ONLY when every requested parameter the adapter provides from the site table verifies as `PASS`. A requested parameter that does not appear on the site (verdict `UNKNOWN`) SHALL NOT block a candidate at Gate 1 — it is deferred to the datasheet stage. A candidate for which any table-provided parameter `FAIL`s SHALL be dropped and SHALL NOT be enriched. Gate 1 SHALL NOT fetch any datasheet.

#### Scenario: All table-provided parameters pass, some unknown

- **WHEN** a candidate's table values for the requested parameters are all `PASS`, and other requested parameters are `UNKNOWN` (absent from the site)
- **THEN** Gate 1 advances the candidate to the datasheet enrichment stage

#### Scenario: A table-provided parameter fails

- **WHEN** at least one requested parameter the table provides yields a `FAIL` verdict (even a single failing parameter is enough)
- **THEN** Gate 1 drops the candidate and it is not enriched

### Requirement: Datasheet-link resolution for Gate 1 survivors

Between Gate 1 and enrichment, the management layer SHALL resolve a candidate's datasheet link by calling the producing adapter's resolution operation for that candidate (see the manufacturer-adapters capability). When the operation returns a URL, the pipeline SHALL carry it on the candidate as `datasheet_url`; when it returns `None`, the candidate's `datasheet_url` SHALL remain `None`.

Resolution SHALL be attempted ONLY for a Gate 1 survivor that has at least one site-missing (`UNKNOWN`) requested parameter — that is, only for a candidate that is actually about to be enriched. The link exists solely to fetch that candidate's datasheet; a survivor whose requested parameters all passed from the table needs no datasheet, so resolving its link would buy nothing and, for a source that resolves by fetching a product page, would cost a request for a page never used.

Resolution SHALL NOT be attempted for candidates dropped at Gate 1, nor during retrieval. Placing it after Gate 1 is what bounds its cost: it scales with the few candidates needing enrichment rather than with the size of the source's catalogue.

The management layer SHALL NOT contain per-site knowledge of where a datasheet link lives or how to reach it; it SHALL only ask the adapter. A resolution failure SHALL be contained per candidate and SHALL NOT abort the run; the affected candidate proceeds with `datasheet_url` as `None`, which is a "No datasheet access" condition.

#### Scenario: A survivor needing enrichment has its link resolved

- **WHEN** a Gate 1 survivor has at least one requested parameter left `UNKNOWN` by the site
- **THEN** the pipeline asks the producing adapter to resolve that candidate's datasheet link
- **AND** the resolved link is used to fetch its datasheet

#### Scenario: A survivor needing no enrichment is not resolved

- **WHEN** a Gate 1 survivor has every requested parameter already `PASS` from the table
- **THEN** no datasheet-link resolution is attempted for it
- **AND** no request is made on its behalf

#### Scenario: Resolution is asked of the adapter, not performed by the pipeline

- **WHEN** the pipeline resolves a candidate's datasheet link
- **THEN** it calls the producing adapter's resolution operation
- **AND** the pipeline itself contains no per-site link-discovery logic

#### Scenario: Candidates dropped at Gate 1 are never resolved

- **WHEN** retrieval returns many candidates and only a few pass Gate 1
- **THEN** datasheet-link resolution is attempted only among the Gate 1 survivors

#### Scenario: A failed resolution leaves the candidate without a link

- **WHEN** an adapter's resolution operation returns `None` for a candidate
- **THEN** that candidate's `datasheet_url` stays `None` and the run continues
- **AND** the candidate is treated as having no datasheet access

### Requirement: Datasheet enrichment of the parameters missing from the site

For each Gate 1 survivor, the enrichment stage SHALL determine the requested parameters that do not appear on the site (verdict `UNKNOWN`) and SHALL resolve those, and only those, from the candidate's datasheet. When the candidate has a `datasheet_url`, the stage SHALL fetch the datasheet PDF, extract its text, run the existing LLM extractor requesting ONLY the missing parameter names, map the result to `RawValue` via the existing datasheet mapping, and merge the newly resolved values into a copy of the candidate. Merged values SHALL carry `source="datasheet"`; the candidate's original table values SHALL NOT be overwritten. A survivor whose requested parameters are already all `PASS` (nothing missing) SHALL skip enrichment entirely — its datasheet link is not resolved, no datasheet PDF is downloaded, and no extractor runs for it.

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
- **AND** no datasheet-link resolution is attempted for it

### Requirement: Enrichment preserves component identity

Enrichment SHALL keep the site-scraped parameters and the datasheet-scraped parameters bound to the SAME component. The enriched candidate SHALL retain the original candidate's identity (`model`, `manufacturer`, `url`, and its `datasheet_url`), and the datasheet-resolved values SHALL be merged into that candidate's own `raw_params` dictionary, keyed by the SAME canonical parameter name the ontology, the adapters, and the verifier use. The datasheet fetched SHALL be the one at that candidate's own `datasheet_url`, so a datasheet is never associated with a different component. There SHALL be no separate cross-list matching step; identity travels with the candidate object from retrieval through both gates.

#### Scenario: Table and datasheet values live on one candidate keyed by canonical name

- **WHEN** a candidate's `Temperature` is resolved from its datasheet and `freq_range` came from the table
- **THEN** both appear in the same candidate's `raw_params`, keyed `Temperature` and `freq_range`
- **AND** the enriched candidate has the same `model`, `manufacturer`, and `url` as the original

#### Scenario: A candidate is enriched only from its own datasheet

- **WHEN** enrichment fetches a datasheet for a candidate
- **THEN** it uses that candidate's own `datasheet_url`, not another candidate's

### Requirement: Enrichment requires a datasheet URL

Datasheet enrichment SHALL run only for candidates that carry a non-empty `datasheet_url` **after the resolution stage has run**. A survivor still without a `datasheet_url` and with at least one site-missing parameter SHALL be left unchanged (its `UNKNOWN` parameters stay `UNKNOWN`); a missing `datasheet_url` is one of the "No datasheet access" conditions, so Gate 2 SHALL return such a survivor as `not-verified` (its site parameters all pass), not drop it.

#### Scenario: Candidate without a datasheet URL is not enriched

- **WHEN** a Gate 1 survivor still has no `datasheet_url` after resolution and has at least one site-missing parameter
- **THEN** no datasheet fetch is attempted for it
- **AND** it is returned by Gate 2 as `not-verified`

### Requirement: Gate 2 assigns each candidate a result outcome of match, not-verified, or dropped

After enrichment, Gate 2 SHALL re-verify each candidate against the same `QuerySpec` and assign one of three outcomes:

- **`match`** — every requested parameter, those passing from the table AND those resolved from the datasheet, verifies as `PASS`. The candidate is returned.
- **`not-verified`** — every requested parameter the **site** provides verifies as `PASS` (Gate 1 already guaranteed this) and **no** parameter `FAIL`s, but at least one requested parameter remains `UNKNOWN` **because the datasheet could not be accessed** (one of the "No datasheet access" conditions), **AND at least 80% of the parameters the user entered verify as `PASS`** (the coverage threshold below). Such a candidate is returned, tagged `not-verified`. A would-be `not-verified` candidate **below** the 80% threshold SHALL be dropped.
- **dropped** — the candidate SHALL NOT appear in the result when EITHER: (a) any requested parameter `FAIL`s (from the table or the datasheet); OR (b) a requested parameter stays `UNKNOWN` even though its datasheet **was** successfully accessed and read — i.e. the datasheet was consulted and is simply silent on that parameter. An `UNKNOWN` that is NOT caused by a datasheet-access failure never yields `not-verified`; it drops the candidate.

A `FAIL` always wins: a candidate with any failing parameter is dropped even if other parameters are unverified. `not-verified` is reserved for the narrow case where the only thing preventing a `match` is that the datasheet **could not be accessed** — never a failing parameter, and never a parameter left `UNKNOWN` by a datasheet that was read successfully but did not state it.

#### Scenario: Datasheet parameters all pass → match

- **WHEN** every parameter resolved from the datasheet verifies as `PASS` and no table parameter failed
- **THEN** the candidate's result outcome is `match` and it is returned (with its link)

#### Scenario: Datasheet inaccessible but site parameters all pass → not-verified

- **WHEN** a Gate 1 survivor (all its site parameters `PASS`) has at least one requested parameter still `UNKNOWN` **because its datasheet could not be accessed**, and no parameter `FAIL`s
- **THEN** the candidate is returned with result outcome `not-verified`

#### Scenario: Datasheet accessed but silent on the parameter → dropped

- **WHEN** a Gate 1 survivor's datasheet was fetched and read successfully but does not state a requested site-missing parameter, so it stays `UNKNOWN` (no access failure, no `FAIL`)
- **THEN** the candidate is dropped and does NOT appear in the result — it is not `not-verified`

#### Scenario: A datasheet parameter fails the requirement → dropped

- **WHEN** a parameter resolved from the datasheet `FAIL`s the requirement
- **THEN** the candidate is dropped and does not appear in the result, even if another parameter was unverified

### Requirement: "No datasheet access" is a defined set of conditions

The pipeline SHALL treat a candidate's datasheet as **inaccessible** — the trigger for a `not-verified` outcome — under ANY of the following conditions, and ONLY these:

1. The candidate has no datasheet link once the resolution stage has run (`datasheet_url` is `None` or empty) — either because the source publishes no datasheet link for the part, or because resolving a product-page-only link failed.
2. The datasheet fetch fails — a network/connection error, a timeout, or a non-success HTTP status (`DatasheetFetchError`).
3. The response is not a usable PDF — e.g. an HTML page (such as an unresolved viewer wrapper) or any body without a `%PDF` signature (`DatasheetFetchError`).
4. The PDF is unreadable — corrupt, encrypted, or otherwise unparseable (`DatasheetFetchError`).
5. The extractor cannot run — the optional `llm` dependency is unavailable, or the extraction call itself errors out.

A datasheet that is **fetched and parsed successfully but is simply silent** on a requested parameter is NOT a "no access" condition — access succeeded. Such a parameter stays `UNKNOWN` and, per Gate 2, **drops** the candidate; it does NOT make it `not-verified`. In all cases the stage SHALL leave the affected parameters `UNKNOWN` and SHALL NOT abort the run.

#### Scenario: A datasheet-access failure yields not-verified

- **WHEN** a Gate 1 survivor (site parameters all `PASS`, nothing `FAIL`) hits any of conditions 1–5 for its still-`UNKNOWN` parameters
- **THEN** the candidate is not dropped for that failure and is returned as `not-verified`

#### Scenario: An accessible-but-silent datasheet does not yield not-verified

- **WHEN** the datasheet is fetched and parsed but does not state a requested site-missing parameter
- **THEN** the condition is NOT "no datasheet access"
- **AND** the parameter stays `UNKNOWN` and the candidate is dropped (not returned)

### Requirement: not-verified candidates must meet an 80% pass-coverage threshold

A candidate that would be returned as `not-verified` (its datasheet could not be accessed, so some requested parameters stay `UNKNOWN`) SHALL be included in the result ONLY when at least **80%** of the parameters the user entered verify as `PASS`. Coverage is computed as:

> `coverage = (number of the user's requested parameters whose verdict is PASS) / (total number of parameters the user entered)`

where the denominator is the count of constraints in the `QuerySpec`. A `not-verified` candidate with `coverage >= 0.80` is returned; one below `0.80` is dropped and does NOT appear in the result. This threshold applies ONLY to the `not-verified` outcome — a `match` candidate has every requested parameter `PASS` (100% coverage) and always qualifies. The threshold never rescues a candidate that has any `FAIL` (a `FAIL` still drops it regardless of coverage).

#### Scenario: not-verified at or above 80% is shown

- **WHEN** the user entered 5 parameters, a `not-verified` candidate has 4 of them `PASS` (from the site) and 1 `UNKNOWN` (datasheet inaccessible), and none `FAIL`
- **THEN** coverage is 80% and the candidate is returned as `not-verified`

#### Scenario: not-verified below 80% is dropped

- **WHEN** the user entered 5 parameters and a `not-verified` candidate has only 3 of them `PASS` (2 `UNKNOWN` from an inaccessible datasheet), none `FAIL`
- **THEN** coverage is 60%, below the threshold, and the candidate is dropped

#### Scenario: The threshold does not apply to match

- **WHEN** a candidate is a full `match` (every requested parameter `PASS`)
- **THEN** its coverage is 100% and the threshold never excludes it

### Requirement: Result output contract per returned product

For every returned candidate (outcome `match` or `not-verified`), the pipeline result SHALL expose these fields, and only these, as the product's result — matching what the front-end form displays:

- **product name** — the candidate's `model`.
- **manufacturer** — the candidate's `manufacturer`.
- **product URL** — the candidate's `url`: the part's page on the manufacturer's site, unchanged from what the search flow returns today. This is the result's only link.
- **verdicts** — the result outcome, `match` or `not-verified`.

The result SHALL NOT expose the candidate's `datasheet_url`. That field exists solely as the enrichment stage's **input**: the pipeline reads the datasheet so the user does not have to, and the extracted parameters — not the link — are what the datasheet contributes to the result. A user who wants the datasheet itself opens the product URL and reaches it from there.

The candidate's `source` field SHALL NOT be part of the returned result — it is an internal/front-end-presentation detail (e.g. a GUI column), not a product-identifying result field.

#### Scenario: A returned product exposes name, manufacturer, the product link, and outcome

- **WHEN** the pipeline returns a candidate
- **THEN** the result carries its product name (`model`), manufacturer, its product URL, and its `match`/`not-verified` outcome
- **AND** the result does not include the candidate's `source`
- **AND** the result does not include the candidate's `datasheet_url`

#### Scenario: The datasheet link is used but never surfaced

- **WHEN** a candidate's datasheet is fetched and its missing parameters extracted during enrichment
- **THEN** the resolved `datasheet_url` is used to fetch that datasheet
- **AND** the parameters it yields appear in the candidate's verdicts, while the link itself does not appear in the result

#### Scenario: A fully verified product is tagged match

- **WHEN** a returned candidate had every requested parameter `PASS` (site and datasheet)
- **THEN** its result verdicts value is `match`

#### Scenario: A site-verified product with an inaccessible datasheet is tagged not-verified

- **WHEN** a returned candidate had all site parameters `PASS` but its datasheet could not be accessed for a site-missing parameter
- **THEN** its result verdicts value is `not-verified`

### Requirement: Fetch datasheet text from a URL

The datasheet layer SHALL obtain datasheet text from a PDF **URL** as its public entry point (`datasheet_text_from_url`). It SHALL download the PDF into memory (no temporary file written), verify the response is actually a PDF, and extract its page text. The PDF→text parsing SHALL be a pure internal step that operates on the downloaded bytes, so it carries no filesystem or network assumptions and is testable without the wire. A fetch that fails — a network/HTTP error, a response that is not a PDF (e.g. an HTML error page served with status 200), or an unparseable PDF — SHALL raise a single well-defined error (`DatasheetFetchError`) the pipeline can catch and treat as "not enriched", rather than aborting the run.

#### Scenario: Datasheet text is produced from a URL

- **WHEN** enrichment is given a candidate's `datasheet_url`
- **THEN** the PDF is downloaded into memory and its page text is extracted for the LLM extractor
- **AND** no temporary file is written to disk

#### Scenario: A non-PDF response is rejected

- **WHEN** the URL returns a non-PDF body (e.g. an HTML error page) even with a success status
- **THEN** `DatasheetFetchError` is raised and the candidate is left unenriched

#### Scenario: A failed fetch is contained

- **WHEN** downloading or parsing a candidate's datasheet PDF fails
- **THEN** `DatasheetFetchError` is raised, the candidate is left unenriched, and the rest of the pipeline continues
