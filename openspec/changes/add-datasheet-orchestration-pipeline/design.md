## Context

The search flow today lives in `rf_finder/search.py::search_and_verify`: it loads every adapter that supports the requested `component_type`, calls `adapter.search(spec)` to get `Candidate`s built from the site's results table, verifies each with `verifier.verify()`, and returns them ranked `match → partial → fail`. It is a single pass — a requested parameter absent from the listing page stays `UNKNOWN`, so the candidate can only surface as `partial`; the part's datasheet is never consulted. There is no explicit management layer: `search_and_verify` is a thin helper, not an owner that coordinates retrieval, verification, and datasheet enrichment as one flow.

The datasheet layer already exists as decoupled building blocks but is unwired:
- `datasheet/pdf.py::datasheet_text_from_pdf(path)` — text from a **local** PDF only.
- `datasheet/extractor.py::extract_rf_parameters(text, requested_parameters)` — LLM extraction, returns `{name: {unit,min,typ,max,value,condition} | None}` for exactly the requested names; needs the `llm` extra (`genaifabric`) and a provider.
- `datasheet/mapping.py::to_raw_params(params)` — maps that extractor output to `{canonical_name: RawValue}`, dropping not-found/ambiguous entries.

`Candidate` (in `models.py`) has `url` (product page, display-only) but no datasheet link, and is a `@dataclass(frozen=True)`. Where the per-part **datasheet link** lives varies by site: most sources publish it on the page the adapter already scrapes (RWM and VectraWave parse it today; Marki has a Datasheet column its adapter currently ignores), 3rWave has none at all, and **Mini-Circuits publishes it only on a per-part product page** — its 789-row `Amplifiers.html` carries no datasheet link, so the adapter cannot read one during `search()` without a fetch per row. The adapter therefore owns the link in both senses: reading it inline when it is free, resolving it on demand when it is not. `verify()` already produces per-parameter `PASS`/`FAIL`/`UNKNOWN` verdicts and an aggregate `overall`, which is exactly the signal both gates need.

This change introduces the **management layer** that owns the flow retrieve → Gate 1 → datasheet-enrich → Gate 2, with the advisor's semantics: a candidate advances past Gate 1 only when every **site-provided** parameter passes; then the **site-missing** parameters are pulled from the candidate's datasheet; and the candidate is returned only when those also all pass.

## Goals / Non-Goals

**Goals:**
- A dedicated management layer that is the single owner of the search flow and coordinates the adapter, verifier, and datasheet layers (which stay decoupled from each other).
- One orchestration entry point that runs the four stages and returns each accepted part (with its link) tagged `match` or `not-verified`.
- Reuse `verify()` as the sole comparator — gates are policy over its verdicts.
- Reuse the existing datasheet building blocks with no new mapping layer.
- Read the datasheet link from the candidate (`datasheet_url`, scraped from the site by the adapter) and enrich only Gate 1 survivors, only for their missing parameters.
- Keep the table-only path working with no `llm` extra and no network for datasheets when nothing needs enriching.

**Non-Goals:**
- Per-site link-discovery logic in the management layer — *where* a datasheet link lives and how to reach it is adapter knowledge. The layer only asks the adapter to resolve a candidate's link (D3); it never learns a site's page structure.
- Fetching per-part product pages during retrieval — `search()` returns every listed part, so a per-part fetch there costs one request per catalogue row (D3).
- Surfacing candidates with any failing parameter, or `partial` candidates whose datasheet was read but simply did not state a parameter — those are dropped. The result is `match` plus the narrow `not-verified` outcome (site-verified parts whose datasheet could not be accessed and that clear the 80% coverage bar).
- Caching datasheet fetches/extractions — out of scope by request; each survivor's datasheet is fetched and extracted as needed. A durable cache remains the separate `implement-response-cache` future change.
- Changing `verify()`'s comparison rules, the ontology, or the form.

## Decisions

### D1 — The management layer is a new `rf_finder/pipeline.py`; `search.py` stays a retrieval helper
The management layer is `run_pipeline(spec, *, on_source=None)` in a new `rf_finder/pipeline.py`. It owns the four-stage flow and is the only place that wires adapters → `verify()` → datasheet together; the CLI (`__main__.py`) and GUI (`ui/gui.py`) switch their one call site from `search_and_verify` to `run_pipeline`. It reuses `search.py`'s `_sources_for` for adapter selection and the same `on_source(outcome, adapter, payload)` progress hook `search_and_verify` already defines, so the front-end progress callbacks port over unchanged.
- *Alternative considered:* extend `search_and_verify` in place. Rejected — it is deliberately the "single-pass, no side effects, no LLM" core; overloading it with network/LLM stages would couple the cheap path to the expensive one. A separate management layer keeps a table-only path for tests and offline use, and makes the "one owner of the flow" boundary explicit.

### D2 — Gates are pure policy over `verify()` verdicts
- **Gate 1:** `v = verify(spec, cand)`; the candidate advances iff no verdict is `FAIL`. Because a parameter the table provides is always `PASS` or `FAIL` (never `UNKNOWN`), "no `FAIL`" is exactly "every site-provided parameter passes" — the advisor's framing — while `UNKNOWN` (site-missing) params are deferred, not blocking. This is `v.overall != "fail"`.
- **Gate 2:** after enrichment, `verify()` again against the *same* `QuerySpec`, then assign one of three outcomes from its verdicts (see D7/D8):
  - `match` — no `FAIL` and no `UNKNOWN` (every requested parameter passes). Returned.
  - `not-verified` — no `FAIL`, but ≥1 requested parameter is still `UNKNOWN`, **every such `UNKNOWN` is caused by a datasheet-access failure** (D7's conditions), **and** coverage `≥ 0.80` (D8). Returned, tagged `not-verified`.
  - dropped — any `FAIL`; **or** an `UNKNOWN` left by a datasheet that *was* read successfully (silent, not an access failure); **or** a would-be `not-verified` below the 0.80 coverage bar. Not returned.
  A `FAIL` always wins over an `UNKNOWN`: a candidate with any failing parameter is dropped even if others are unverified.
- *Alternative considered:* a bespoke gate predicate inspecting `raw_params` directly. Rejected — `verify()` already encodes unit normalization and every comparison rule; re-deriving pass/fail outside it would risk drift (the "single comparison engine" rule).

### D3 — The datasheet link comes from the adapter: inline when free, resolved on demand when not
`Candidate` gains `datasheet_url: str | None = None`. Sources publish the link in one of three ways, and the adapter owns which applies:

1. **On the page the adapter already scrapes** — it reads the link during `search()` and the candidate carries it from retrieval, free. This is the common case (e.g. RWM and VectraWave already parse it today).
2. **Only on a per-part product page** — verified for **Mini-Circuits**: `Amplifiers.html` carries no datasheet link at all; it lives only on `dashboard.html?model=<MODEL>`. Reading it during `search()` would cost **one fetch per listed part** — 789 rows × the 1 s politeness guard ≈ 13 minutes per search — for a link that only a handful of candidates will ever need. So `search()` leaves the field `None` and the adapter resolves it **on demand**.
3. **Nowhere** — the source has no datasheet (e.g. 3rWave, OQ-3W-6); the field stays `None` legitimately.

Every adapter therefore exposes `resolve_datasheet_url(cand) -> str | None`, defaulting to `return cand.datasheet_url` — so cases 1 and 3 need no work, and only a case-2 adapter overrides it. The management layer calls this for Gate 1 survivors (D10) and holds no per-site knowledge.

Case 2 must not be collapsed into case 3. A case-2 part **has** a datasheet; reporting `None` would silently deny it one, forcing every Mini-Circuits result to `not-verified` (via "no datasheet access" condition 1) and never `match`.

- *Alternative considered:* derive the PDF URL by pattern (`/pdfs/<MODEL>.pdf`) and skip the fetch entirely. Rejected — measured at 37/40 on a live sample, but it **404s wherever the datasheet filename differs from the model**, which is systematic in the ZFL/ZHL/ZVA coaxial families where suffix variants share a base datasheet (`ZHL-10M4G21W1X+` → `ZHL-10M4G21W1+.pdf`, `ZHL-2X-S+` → `ZHL-2-S+.pdf`, `ZFL-2500VHX+` → `ZFL-2500VH+.pdf`). Guessing silently loses the datasheet for exactly the parts whose naming is irregular; the product page is authoritative.
- *Alternative considered:* a bulk source, so Mini-Circuits could stay case 1. Rejected — none exists: "Export to Excel" is a POST to the server-side action `Amplifiers.downloadExcelFile` mirroring the visible columns, and `Amplifiers.html`, `Amplifiers_tab2.html` and `products/Amplifiers_tab3.html` contain zero per-part `/pdfs/` links.

### D10 — Resolution is its own stage, between Gate 1 and enrichment, only for candidates about to be enriched
The pipeline gains a stage: for each Gate 1 survivor that still has an `UNKNOWN` requested parameter, call the producing adapter's `resolve_datasheet_url(cand)` and carry the result via `dataclasses.replace(cand, datasheet_url=...)` — the same copy mechanism enrichment already uses (D4).

Two bounds keep it cheap. **After Gate 1**, so the set is the handful of candidates that survived rather than the 789-row catalogue. **Only where something is missing**, because the link is purely enrichment's input (D9): a survivor whose requested parameters all passed from the table needs no datasheet, so resolving its link would buy nothing — and for a case-2 adapter would spend a request fetching a product page nobody reads.

Retrieval must therefore keep each candidate's producing adapter so the pipeline knows whom to ask; `search_and_verify` currently flattens them into one list, so the pipeline tracks `(adapter, candidate)` pairs during stage 1.

A resolution failure returns `None` rather than raising, collapsing into "no datasheet access" condition 1 — no new failure mode, and D7's five conditions stand unchanged.
- *Alternative considered:* fold resolution into the enrichment function instead of making it a stage. Rejected — a distinct stage is what keeps "ask the adapter where the link is" (site knowledge) separable from "read the PDF" (the datasheet layer). Merging them would push site knowledge into the datasheet path, crossing the layer boundary the management layer exists to enforce.

### D4 — Enrich by merging into a copy; datasheet never overwrites the table
`Candidate` is frozen, so enrichment builds a new `Candidate` via `dataclasses.replace(cand, raw_params={**cand.raw_params, **datasheet_raw}, source="datasheet")`. The merge only adds keys that were missing (the `UNKNOWN` set); table keys are never replaced, so a site value always wins over a datasheet value for the same parameter. The requested-parameter list handed to `extract_rf_parameters` is exactly the `UNKNOWN` canonical names from Gate 1's verdicts — never the ones the table already answered. `source="datasheet"` on the enriched copy makes `verify()` label its `confidence` accordingly. Per-`RawValue` provenance is out of scope; `RawValue` stays unchanged.

### D5 — `pdf.py` becomes URL-only, split fetch from parse
`pdf.py` exposes a single public entry point, `datasheet_text_from_url(url)`, and drops the old local-file `datasheet_text_from_pdf(path)` (the flow only ever has a remote `datasheet_url`). Concerns are split so parsing stays testable without the wire:
- `datasheet_text_from_url(url)` — fetch with `httpx` (matching the adapters: `User-Agent`, `follow_redirects`, `timeout`, `raise_for_status`), keep the bytes in memory (`io.BytesIO` — no temp file), verify the body is a real PDF (`%PDF` signature / Content-Type), then parse.
- `_text_from_stream(source)` — internal pure core: `pdfplumber.open` on a path *or* a stream, reusing the existing `_join_page_text`.
Any failure (network, HTTP status, non-PDF response, unparseable PDF) raises `DatasheetFetchError`, which the management layer catches per-candidate. TLS: rely on the project's `truststore` setup (the `etrog-ssl-fail` skill) so `httpx` verifies against the Windows cert store — never `verify=False`. The local-file test path is replaced by tests that stub `httpx.get` and the parse core, so no real PDF or network is needed.

### D6 — Resilience mirrors `search_and_verify`
One adapter raising, one PDF failing to download, or one extraction erroring never aborts the run: the affected source/candidate is skipped (reported via `on_source` where applicable) and the rest complete. The LLM/`requests` imports stay lazy (inside the enrichment functions) so importing `pipeline` is free and the table-only path needs neither the `llm` extra nor network.

### D7 — Enrichment records whether each candidate's datasheet was *accessible*
This boolean is what separates `not-verified` from `dropped` at Gate 2. A candidate's datasheet is **inaccessible** under exactly the five conditions the spec fixes, and only these: (1) no `datasheet_url`; (2) the fetch fails — network/connection error, timeout, or non-success HTTP status (`DatasheetFetchError`); (3) the response is not a usable PDF — an HTML wrapper or any body without a `%PDF` signature (`DatasheetFetchError`); (4) the PDF is unreadable — corrupt/encrypted (`DatasheetFetchError`); (5) the extractor cannot run — the `llm` extra is unavailable or the extraction call errors. Otherwise the datasheet was **accessed** — fetched, parsed, and the extractor ran — and any parameter it did not resolve is *silent*, not inaccessible. Because there is one fetch per candidate, accessibility is a single boolean carried alongside the enriched candidate (e.g. `datasheet_accessible`): when it is `False`, every still-`UNKNOWN` requested param is attributed to the access failure (→ `not-verified`, subject to D8); when it is `True`, a still-`UNKNOWN` param is a silent-datasheet miss (→ dropped). A missing `datasheet_url` is condition 1 — inaccessible — so its survivor is `not-verified`, **not** dropped (reversing the old "no link → drop").

### D8 — `not-verified` requires ≥80% pass-coverage
A candidate that would be returned as `not-verified` is included only when `coverage = (requested params whose verdict is PASS) / (total params the user entered) ≥ 0.80`; below that it is dropped. The denominator is the count of constraints in the `QuerySpec`, and the numerator comes from the same `verify()` verdicts the gates already hold — no new comparison. The bar applies **only** to `not-verified`: a `match` is 100% coverage by construction and always qualifies, and a `FAIL` is dropped regardless of coverage (the threshold never rescues a failing candidate).
- *Alternative considered:* return every access-failure survivor as `not-verified`. Rejected — the user set an 80% floor so a barely-covered part isn't presented as a near-match.

### D9 — The result exposes the product link only; the datasheet URL is internal
`run_pipeline` returns accepted candidates, and the product-facing result carries four fields: product name (`model`), manufacturer (`manufacturer`), product URL (`url`), and the outcome tag (`match`/`not-verified`). The result's link is the candidate's `url` — **unchanged from what the flow returns today**. The outcome is carried on the result so the front-ends render it without recomputing. The candidate's `source` is an internal/presentation detail (a GUI column) and is **not** part of the result contract, even though enrichment sets `source="datasheet"` (D4) for `verify()`'s confidence labelling.

`datasheet_url` is **not** a result field. It exists only as enrichment's input: the pipeline reads the datasheet so the user does not have to, and what the datasheet contributes to the result is the extracted **parameters**, not the link. A user who wants the datasheet itself opens the product page and finds it there.
- *Alternative considered:* surface `datasheet_url` as a result field of its own. Rejected — the datasheet is an input to verification, not a deliverable; the product page already leads to it, so a second link adds a column that duplicates a click.
- *Alternative considered (the original contract):* one link field carrying `datasheet_url` with a fallback to `url`. Rejected — it makes an absent datasheet indistinguishable from a present one. Mini-Circuits shows the cost: its `url` is `modelSearch.html`, a page `robots.txt` disallows, which the UI would then present as the part's datasheet. Keeping the result's single link honestly *being* the product page avoids the ambiguity without needing a second field.

## Risks / Trade-offs

- **LLM cost/latency on large survivor sets** → Gate 1 runs first (cheap, no network), so only survivors are enriched, and only for their missing parameters; enrichment can be parallelized later if needed.
- **`not-verified` surfaces parts whose datasheet couldn't be confirmed** → deliberately narrow: only site-verified parts (all table params `PASS`, none `FAIL`) whose remaining `UNKNOWN`s are all from a datasheet-access failure (D7) and that clear the 80% coverage bar (D8). A datasheet that was read but silent, or any `FAIL`, still drops the candidate — so `not-verified` never hides a real mismatch. The management layer still computes the `partial`/`fail` outcomes internally, so a later flag could re-expose more without redesign.
- **A site row may lack a datasheet link** → then `datasheet_url` is `None` after resolution; this is "no datasheet access" condition 1 (D7), so the candidate's site-missing params stay `UNKNOWN` and Gate 2 returns it as `not-verified` when it clears 80% coverage (D8), rather than dropping it. The field defaults to `None`, so adapters that don't set it construct unchanged.
- **Resolution adds one request per Gate 1 survivor for case-2 adapters** → bounded by the survivor count, not the catalogue, and only paid by adapters that need it (Mini-Circuits today). If a query is loose enough to leave hundreds of survivors, that cost is real; the existing per-adapter rate guard applies, and the separate `implement-response-cache` change would amortize it. Sequential-vs-concurrent resolution shares the open question already tracked for enrichment.
- **Only Mini-Circuits is *confirmed* case 2** → six adapters (Amcom, ADI, MACOM, Microchip, UMS, GuerrillaRF, Qorvo) have never been checked, and AmcomUSA is already known to use table+detail pages. If several turn out to be case 2, the D3 seam is the normal path rather than an exception — which is why it is a first-class part of the adapter contract and not a Mini-Circuits special case. The per-adapter verification pass (tasks §5) settles this before the adapters are written.
- **The pipeline will now download datasheet PDFs, which adapters previously never did** → e.g. `marki.py` documents "datasheet PDFs are not fetched programmatically" as its compliance stance. Carrying a link and fetching it are different acts; each site's `robots.txt` must be checked for the PDF path before enabling enrichment there (tasks §5).
- **LLM extraction can be wrong** → `extract_rf_parameters` forbids guessing (returns `null` when absent) and `to_raw_params` drops ambiguous/unit-missing values, so an unresolved parameter stays `UNKNOWN` → dropped, never a wrongful match. A mis-extracted value could still cause a wrong `FAIL`/`match`; mitigated by the "never guess" contract and `datasheet` confidence labelling.
- **Frozen-dataclass copy churn** → `replace()` allocates a new `Candidate` per enriched survivor; negligible at these result sizes.

## Migration Plan

1. Add `Candidate.datasheet_url: str | None = None` (defaulted — no adapter change required to construct). Independent of every open question below, so it lands first.
2. Rewrite `datasheet/pdf.py` to URL-only (`datasheet_text_from_url` + `_text_from_stream` + `DatasheetFetchError`); update its exports and tests. *(done)*
3. Add the default `Adapter.resolve_datasheet_url(cand) -> str | None` returning `cand.datasheet_url` — inert until the pipeline calls it, and satisfied by every existing adapter without change.
4. Add `rf_finder/pipeline.py` — the management layer — with `run_pipeline`, the resolution stage (D10), and the enrichment helpers.
5. Point `__main__.py` and `ui/gui.py` at `run_pipeline`; keep `search_and_verify` for the table-only tests.
6. Verify each source live to classify it case 1/2/3 and check `robots.txt` for its PDF path, then per adapter: read the link inline (case 1), override `resolve_datasheet_url` (case 2), or leave `None` (case 3).

Rollback: revert the call-site switch in step 4; the new module and the defaulted field are inert without callers.

## Open Questions

- Should enrichment fan out concurrently across survivors, or stay sequential for the first cut? (Default: sequential; parallelize if latency warrants.)
- When a datasheet resolves a parameter to a **range/list** whose comparison is `contains`, the existing mapping/verify handle it — but do any requested datasheet-only params need extractor-prompt tuning beyond the current `Temperature`/`MSL`/`length`/`width` coverage? (Track per adapter.)
- Confidence display: this change sets `confidence="datasheet"` on enriched matches but the CLI still does not render confidence (that is `implement-reporter`). Left as-is.
