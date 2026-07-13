## 1. Data model: datasheet link on Candidate

- [ ] 1.1 Add `datasheet_url: str | None = None` to `Candidate` in `rf_finder/models.py` (defaulted so existing constructions are unchanged)
- [ ] 1.2 Update the `core-data-models` field list / docstring to mention `datasheet_url`
- [ ] 1.3 Test: a `Candidate` built without `datasheet_url` has `datasheet_url is None`; one built with it exposes the link

## 2. Datasheet fetch-by-URL

- [ ] 2.1 Add `DatasheetFetchError` and `datasheet_text_from_url(url)` to `rf_finder/datasheet/pdf.py` — download the PDF (lazy `requests` import, project TLS handling) and reuse `_join_page_text`/`pdfplumber`
- [ ] 2.2 Raise `DatasheetFetchError` on network error, HTTP error, non-PDF response, or unparseable PDF
- [ ] 2.3 Export the new helper/error from `rf_finder/datasheet/__init__.py`
- [ ] 2.4 Test (with a fake/stubbed downloader): a URL yields the same text `datasheet_text_from_pdf` would; a failed download raises `DatasheetFetchError`

## 3. Management layer: pipeline module

- [ ] 3.1 Create `rf_finder/pipeline.py` with `run_pipeline(spec, *, on_source=None) -> list[VerifiedCandidate]`, reusing `search._sources_for` and the `on_source` hook
- [ ] 3.2 Stage 1 (retrieve): gather candidates from every supporting adapter, one bad source skipped via `on_source("error"/"empty"/"ok", ...)`
- [ ] 3.3 Gate 1: `verify()` each candidate; keep only those with no `FAIL` verdict (every site-provided parameter passes; `UNKNOWN` deferred)
- [ ] 3.4 Enrichment: for each survivor compute the `UNKNOWN` requested params; if `datasheet_url` is set, fetch text, call `extract_rf_parameters(text, missing)`, map via `to_raw_params`, and merge into a `dataclasses.replace` copy with `source="datasheet"` (never overwriting table values); skip survivors with nothing missing
- [ ] 3.5 Per-run extraction cache keyed by `(datasheet_url, frozenset(missing_params))` so shared datasheets/re-verifies fetch+extract at most once
- [ ] 3.6 Contain per-candidate enrichment failures (`DatasheetFetchError`, extraction/LLM errors) so the run continues; keep `requests`/LLM imports lazy
- [ ] 3.7 Gate 2: re-`verify()` enriched candidates; return only those with `overall == "match"`

## 4. Wire front-ends to the management layer

- [ ] 4.1 Point `rf_finder/__main__.py` at `run_pipeline` (result set is now full matches only)
- [ ] 4.2 Point `rf_finder/ui/gui.py` at `run_pipeline`
- [ ] 4.3 Keep `search_and_verify` available for the table-only tests

## 5. Adapters populate datasheet_url from the site

- [ ] 5.1 For each adapter whose site row/detail exposes a per-part datasheet link, read that link into `Candidate.datasheet_url`; leave `None` where no link exists
- [ ] 5.2 Per-adapter test: candidates carry `datasheet_url` when the source row has a datasheet link

## 6. End-to-end tests for the pipeline

- [ ] 6.1 Gate 1 drops a candidate whose table parameter `FAIL`s (never enriched)
- [ ] 6.2 A survivor with a site-missing param is enriched from a stubbed datasheet and returned as a `match` when the datasheet value passes
- [ ] 6.3 A survivor whose datasheet value `FAIL`s, or stays `UNKNOWN` (no `datasheet_url` / fetch fails / datasheet silent), is dropped by Gate 2
- [ ] 6.4 Only site-missing params are requested from the extractor (table-answered params are not re-requested)
- [ ] 6.5 The extraction cache invokes fetch+extract at most once for a shared `(datasheet_url, params)` pair
- [ ] 6.6 A raising adapter / failing datasheet does not abort the run

## 7. Validate

- [ ] 7.1 Run the full test suite
- [ ] 7.2 `openspec validate add-datasheet-orchestration-pipeline --strict`
