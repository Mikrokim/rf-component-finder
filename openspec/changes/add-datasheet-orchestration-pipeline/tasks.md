## 1. Data model: datasheet link on Candidate

- [ ] 1.1 Add `datasheet_url: str | None = None` to `Candidate` in `rf_finder/models.py` — must be the LAST field, since the others have no defaults (defaulted so existing constructions are unchanged)
- [ ] 1.2 Update the `core-data-models` field list / docstring to mention `datasheet_url`
- [ ] 1.3 Test: a `Candidate` built without `datasheet_url` has `datasheet_url is None`; one built with it exposes the link

## 2. Datasheet fetch-by-URL (URL-only)

- [x] 2.1 Rewrite `rf_finder/datasheet/pdf.py` to URL-only: add `DatasheetFetchError`, an internal pure parse core `_text_from_stream(source)` (reusing `_join_page_text`/`pdfplumber`), and the public `datasheet_text_from_url(url)` that fetches with `httpx` into `io.BytesIO` (no temp file); remove the local-file `datasheet_text_from_pdf`
- [x] 2.2 Raise `DatasheetFetchError` on network/HTTP error, non-PDF response (`%PDF`/Content-Type guard), or unparseable PDF; rely on project `truststore` TLS (never `verify=False`)
- [x] 2.3 Update exports in `rf_finder/datasheet/__init__.py` (`datasheet_text_from_url`, `DatasheetFetchError`; drop `datasheet_text_from_pdf`)
- [x] 2.4 Update `tests/test_datasheet_pdf.py`: keep the `_join_page_text` tests; stub `httpx.get` (and the parse core) to test a successful URL fetch, an HTTP error, and a non-PDF response — no real PDF or network

## 3. Adapter contract: on-demand datasheet-link resolution

- [ ] 3.1 Add `resolve_datasheet_url(self, cand: Candidate) -> str | None` to the `Adapter` ABC in `rf_finder/adapters/base.py` as a NON-abstract default returning `cand.datasheet_url` (so all 12 existing adapters satisfy it unchanged)
- [ ] 3.2 Document the contract on the default: return `None` rather than raise when the link cannot be resolved; never fetch per-part pages from `search()`; never fetch a robots-disallowed URL
- [ ] 3.3 Test: the default returns the candidate's existing `datasheet_url` (and `None` when it has none) without making any request

## 4. Management layer: pipeline module

- [ ] 4.1 Create `rf_finder/pipeline.py` with `run_pipeline(spec, *, on_source=None)`, reusing `search._sources_for` and the `on_source` hook
- [ ] 4.2 Stage 1 (retrieve): gather candidates from every supporting adapter, keeping each candidate's producing adapter (`(adapter, candidate)` pairs) so later stages know whom to ask; one bad source skipped via `on_source("error"/"empty"/"ok", ...)`
- [ ] 4.3 Gate 1: `verify()` each candidate; keep only those with no `FAIL` verdict (every site-provided parameter passes; `UNKNOWN` deferred)
- [ ] 4.4 Stage 3 (resolve): for each Gate 1 survivor that has at least one `UNKNOWN` requested param, call `adapter.resolve_datasheet_url(cand)` and carry the result via `dataclasses.replace(cand, datasheet_url=...)`. Survivors with nothing missing are skipped — the link is only enrichment's input, so resolving theirs would cost a request for a datasheet never read
- [ ] 4.5 Contain resolution failures per candidate (adapter raising despite the contract): treat as `None` and continue the run
- [ ] 4.6 Enrichment: for each survivor compute the `UNKNOWN` requested params; if `datasheet_url` is set after resolution, fetch text, call `extract_rf_parameters(text, missing)`, map via `to_raw_params`, and merge into a `dataclasses.replace` copy with `source="datasheet"` (never overwriting table values); skip survivors with nothing missing entirely
- [ ] 4.7 Contain per-candidate enrichment failures (`DatasheetFetchError`, extraction/LLM errors) so the run continues; keep `requests`/LLM imports lazy
- [ ] 4.8 Gate 2: re-`verify()` each enriched candidate against the same `spec`; assign `match` (no `FAIL`, no `UNKNOWN`), `not-verified` (no `FAIL`; every remaining `UNKNOWN` is from a datasheet-access failure; coverage ≥ 0.80), or dropped (any `FAIL`; an `UNKNOWN` from a datasheet that was read but silent; or a `not-verified`-shaped candidate below 0.80) — a `FAIL` always drops
- [ ] 4.9 Track datasheet accessibility per candidate (the five "no access" conditions; condition 1 is "no `datasheet_url` AFTER resolution") so Gate 2 can tell an access-failure `UNKNOWN` (→ `not-verified`) from a silent-datasheet `UNKNOWN` (→ dropped)
- [ ] 4.10 Compute `coverage = (requested params with PASS) / (total params in spec)` and admit a `not-verified` candidate only when `coverage >= 0.80` (never rescues a `FAIL`)
- [ ] 4.11 Tag each accepted candidate with its outcome and expose the result fields — product name (`model`), manufacturer, product URL (`url`, unchanged from today), outcome — keeping BOTH `source` and `datasheet_url` out of the result contract

## 5. Wire front-ends to the management layer

- [ ] 5.1 Point `rf_finder/__main__.py` at `run_pipeline` (result set is now `match` + `not-verified`, each tagged with its outcome)
- [ ] 5.2 Point `rf_finder/ui/gui.py` at `run_pipeline` and surface the `match`/`not-verified` outcome. The results view is otherwise UNCHANGED: no new column, and its link column keeps showing `c.url` and keeps the double-click deep-link exactly as today
- [ ] 5.3 Re-head the existing link column: `gui.py:350` heads the `url` column **"Datasheet URL"**, but it is filled with `c.url` — the product page (`gui.py:331`), which is also what double-click opens (`gui.py:334`). The column always was the product page and stays the product page; only the heading is wrong. Re-head it to **"Product URL"**. No behavior change — same value, same double-click
- [ ] 5.4 Keep `search_and_verify` available for the table-only tests

## 6. Per-source verification pass (prerequisite for §7)

Task 7 cannot be written per adapter until each source is classified. Mini-Circuits proved the "the link is in the table" assumption fails silently. **Verify each source against a live page — not research, not fixtures.**

For each source record: (a) case 1 (link on the already-scraped page) / case 2 (product page only) / case 3 (no datasheet); (b) for case 2, the robots-ALLOWED product-page URL template; (c) whether `robots.txt` allows fetching the PDF path — the pipeline now downloads PDFs, which adapters never did.

- [ ] 6.1 Mini-Circuits — **done, verified**: case 2. Table `<a href>` is `modelSearch.html?model=X` which robots DISALLOWS; the allowed product page is `dashboard.html?model=<urlencoded>` (sitemap-listed), carrying an `<a>` with text `DATASHEET`. `+` MUST be encoded `%2B` or the page returns 200 with NO datasheet link (silent failure). `/pdfs/` is robots-allowed.
- [ ] 6.2 RWM — case 1, link already parsed but misfiled into `url` (`rwmmic.py:281`). Confirm the API's `datasheet` field is absolute; check robots for the PDF path.
- [ ] 6.3 VectraWave — case 1, already parsed and absolutized via `_abs_url` (`vectrawave.py:238`). Check robots for the PDF path.
- [ ] 6.4 Marki — table HAS a Datasheet column the adapter explicitly ignores (`marki.py:94`). Confirm it carries a usable href; **resolve the conflict with `marki.py:44`, which documents "datasheet PDFs are not fetched programmatically"** — carrying a link and fetching it are different acts, so re-check robots for the PDF path before enabling enrichment.
- [ ] 6.5 3rWave — case 3 per OQ-3W-6 (`threerwave.py:144`), no per-part page or datasheet. Confirm still true; if so, `None` is correct and no work follows.
- [ ] 6.6 AmcomUSA — UNVERIFIED. Known to use two-tier table/detail pages, so likely case 2. Verify.
- [ ] 6.7 Analog Devices — UNVERIFIED. Verify.
- [ ] 6.8 MACOM — UNVERIFIED. Verify (embedded-JSON site; the link may be in the JSON payload already fetched → case 1).
- [ ] 6.9 Microchip — UNVERIFIED. Verify (official-API path; the feed may carry a datasheet field → case 1).
- [ ] 6.10 UMS — UNVERIFIED. Verify.
- [ ] 6.11 GuerrillaRF — UNVERIFIED. Verify.
- [ ] 6.12 Qorvo — UNVERIFIED. Verify.
- [ ] 6.13 Record the results as a case-per-source table in this change, and update each adapter's skill with the finding (the skills are where per-site retrieval knowledge lives)

## 7. Adapters supply the datasheet URL

Sized by §6's classification. Case 1 = read inline in `search()`; case 2 = override `resolve_datasheet_url`; case 3 = nothing. Every supplied URL MUST be absolute (resolve relative hrefs against the site's base URL).

- [ ] 7.1 Mini-Circuits (case 2): override `resolve_datasheet_url` — GET `dashboard.html?model={urllib.parse.quote(model, safe='')}`, take the `<a>` whose text is `DATASHEET`, absolutize the href; return `None` on any failure. Keep the existing rate guard. Do NOT fetch from `search()`.
- [ ] 7.2 Mini-Circuits: switch `Candidate.url` from the robots-disallowed `modelSearch.html?model=` to the allowed `dashboard.html?model=` — the real product page, and now also what the result's product-URL field surfaces. This closes the skill's open OQ-2.
- [ ] 7.3 RWM (case 1): move the datasheet link from `url` into `datasheet_url`, and give `url` the product page instead — today `url` holds the PDF (`rwmmic.py:281`), so the result's "Product URL" would show a PDF and the user would have no route to the part's page
- [ ] 7.4 VectraWave (case 1): set the already-parsed per-product PDF href into `datasheet_url`
- [ ] 7.5 Marki (case 1, pending 6.4): stop ignoring the Datasheet column; read its href into `datasheet_url`
- [ ] 7.6 The remaining sources per §6's findings (3rWave: none; Amcom/ADI/MACOM/Microchip/UMS/GuerrillaRF/Qorvo: as classified)
- [ ] 7.7 Per-adapter test: a case-1 adapter's candidates carry an absolute `datasheet_url` from the source page, with no extra request
- [ ] 7.8 Per-adapter test (case 2): `search()` makes NO per-part request and leaves `datasheet_url` as `None`; `resolve_datasheet_url` returns the absolute PDF link from a stubbed product page; a stubbed fetch failure and a product page with no datasheet link both return `None` without raising
- [ ] 7.9 Mini-Circuits regression test: a model whose name contains `+` is URL-encoded (`%2B`) when building the product-page URL — the un-encoded form silently yields a 200 page with no datasheet link

## 8. End-to-end tests for the pipeline

- [ ] 8.1 Gate 1 drops a candidate whose table parameter `FAIL`s (never resolved, never enriched)
- [ ] 8.2 A survivor with a site-missing param is enriched from a stubbed datasheet and returned as a `match` when the datasheet value passes
- [ ] 8.3 A survivor whose datasheet value `FAIL`s is dropped by Gate 2 (even if another requested param is unverified)
- [ ] 8.4 A survivor whose datasheet is read successfully but is silent on a site-missing param (stays `UNKNOWN`) is dropped by Gate 2 — not `not-verified`
- [ ] 8.5 A survivor whose datasheet is inaccessible (no link after resolution, or a stubbed fetch/parse/extractor failure) is returned as `not-verified` when it clears 80% coverage; the same case below 80% coverage is dropped
- [ ] 8.6 Only site-missing params are requested from the extractor (table-answered params are not re-requested)
- [ ] 8.7 A raising adapter / failing datasheet / failing resolution does not abort the run
- [ ] 8.8 The returned result exposes product name, manufacturer, product URL, and the outcome tag; it exposes neither `source` nor `datasheet_url`
- [ ] 8.9 A candidate enriched from its datasheet surfaces the datasheet's PARAMETERS in its verdicts, while the datasheet link itself stays out of the result
- [ ] 8.10 Resolution is attempted only for Gate 1 survivors with a missing param — NOT for a survivor whose params all passed from the table, and NOT for candidates dropped at Gate 1
- [ ] 8.11 The pipeline asks the producing adapter to resolve, and holds no per-site logic (a fake case-2 adapter's `resolve_datasheet_url` is called for its own candidates only)

## 9. Validate

- [ ] 9.1 Run the full test suite
- [ ] 9.2 `openspec validate add-datasheet-orchestration-pipeline --strict`
