## Context

The search flow today lives in `rf_finder/search.py::search_and_verify`: it loads every adapter that supports the requested `component_type`, calls `adapter.search(spec)` to get `Candidate`s built from the site's results table, verifies each with `verifier.verify()`, and returns them ranked `match → partial → fail`. It is a single pass — a requested parameter absent from the listing page stays `UNKNOWN`, so the candidate can only surface as `partial`; the part's datasheet is never consulted. There is no explicit management layer: `search_and_verify` is a thin helper, not an owner that coordinates retrieval, verification, and datasheet enrichment as one flow.

The datasheet layer already exists as decoupled building blocks but is unwired:
- `datasheet/pdf.py::datasheet_text_from_pdf(path)` — text from a **local** PDF only.
- `datasheet/extractor.py::extract_rf_parameters(text, requested_parameters)` — LLM extraction, returns `{name: {unit,min,typ,max,value,condition} | None}` for exactly the requested names; needs the `llm` extra (`genaifabric`) and a provider.
- `datasheet/mapping.py::to_raw_params(params)` — maps that extractor output to `{canonical_name: RawValue}`, dropping not-found/ambiguous entries.

`Candidate` (in `models.py`) has `url` (product page, display-only) but no datasheet link, and is a `@dataclass(frozen=True)`. The per-part **datasheet link is already present on the manufacturer page the adapter scrapes** — the adapter reads it there and carries it on the candidate (the new `datasheet_url` field); the management layer just consumes it. `verify()` already produces per-parameter `PASS`/`FAIL`/`UNKNOWN` verdicts and an aggregate `overall`, which is exactly the signal both gates need.

This change introduces the **management layer** that owns the flow retrieve → Gate 1 → datasheet-enrich → Gate 2, with the advisor's semantics: a candidate advances past Gate 1 only when every **site-provided** parameter passes; then the **site-missing** parameters are pulled from the candidate's datasheet; and the candidate is returned only when those also all pass.

## Goals / Non-Goals

**Goals:**
- A dedicated management layer that is the single owner of the search flow and coordinates the adapter, verifier, and datasheet layers (which stay decoupled from each other).
- One orchestration entry point that runs the four stages and returns only full matches (with each part's link).
- Reuse `verify()` as the sole comparator — gates are policy over its verdicts.
- Reuse the existing datasheet building blocks with no new mapping layer.
- Read the datasheet link from the candidate (`datasheet_url`, scraped from the site by the adapter) and enrich only Gate 1 survivors, only for their missing parameters.
- Keep the table-only path working with no `llm` extra and no network for datasheets when nothing needs enriching.

**Non-Goals:**
- Discovering datasheet links by a *separate* page fetch — the link is already on the listing/product page the adapter scrapes, so it is read there and carried as `Candidate.datasheet_url`; the management layer does not go hunting for it.
- Surfacing partials to the user — the result is only full matches (decided with the user).
- A persistent cross-run cache — caching here is per-run (in-process) to avoid duplicate work within a single search; a durable cache is the separate `implement-response-cache` future change.
- Changing `verify()`'s comparison rules, the ontology, or the form.

## Decisions

### D1 — The management layer is a new `rf_finder/pipeline.py`; `search.py` stays a retrieval helper
The management layer is `run_pipeline(spec, *, on_source=None)` in a new `rf_finder/pipeline.py`. It owns the four-stage flow and is the only place that wires adapters → `verify()` → datasheet together; the CLI (`__main__.py`) and GUI (`ui/gui.py`) switch their one call site from `search_and_verify` to `run_pipeline`. It reuses `search.py`'s `_sources_for` for adapter selection and the same `on_source(outcome, adapter, payload)` progress hook `search_and_verify` already defines, so the front-end progress callbacks port over unchanged.
- *Alternative considered:* extend `search_and_verify` in place. Rejected — it is deliberately the "single-pass, no side effects, no LLM" core; overloading it with network/LLM stages would couple the cheap path to the expensive one. A separate management layer keeps a table-only path for tests and offline use, and makes the "one owner of the flow" boundary explicit.

### D2 — Gates are pure policy over `verify()` verdicts
- **Gate 1:** `v = verify(spec, cand)`; the candidate advances iff no verdict is `FAIL`. Because a parameter the table provides is always `PASS` or `FAIL` (never `UNKNOWN`), "no `FAIL`" is exactly "every site-provided parameter passes" — the advisor's framing — while `UNKNOWN` (site-missing) params are deferred, not blocking. This is `v.overall != "fail"`.
- **Gate 2:** after enrichment, `verify()` again; keep iff `overall == "match"`.
- *Alternative considered:* a bespoke gate predicate inspecting `raw_params` directly. Rejected — `verify()` already encodes unit normalization and every comparison rule; re-deriving pass/fail outside it would risk drift (the "single comparison engine" rule).

### D3 — The datasheet link comes from the candidate, scraped by the adapter
`Candidate` gains `datasheet_url: str | None = None`. Each adapter reads the per-part datasheet link from the same site page it already scrapes for the table row and sets it on the candidate; where a site row has no datasheet link, the field stays `None`. The management layer reads `cand.datasheet_url` and enriches only when it is present. No separate discovery/scrape step is introduced — the link travels with the candidate from retrieval.

### D4 — Enrich by merging into a copy; datasheet never overwrites the table
`Candidate` is frozen, so enrichment builds a new `Candidate` via `dataclasses.replace(cand, raw_params={**cand.raw_params, **datasheet_raw}, source="datasheet")`. The merge only adds keys that were missing (the `UNKNOWN` set); table keys are never replaced, so a site value always wins over a datasheet value for the same parameter. The requested-parameter list handed to `extract_rf_parameters` is exactly the `UNKNOWN` canonical names from Gate 1's verdicts — never the ones the table already answered. `source="datasheet"` on the enriched copy makes `verify()` label its `confidence` accordingly. Per-`RawValue` provenance is out of scope; `RawValue` stays unchanged.

### D5 — `datasheet_url` fetch path added to `pdf.py`
Add `datasheet_text_from_url(url)` alongside `datasheet_text_from_pdf(path)`: download the PDF at the candidate's `datasheet_url` (via `requests`, respecting the project's TLS handling — see the `etrog-ssl-fail` skill for the corporate-proxy cert case) to a scratch file or an in-memory buffer, then reuse `_join_page_text` / `pdfplumber`. Failures (network, HTTP error, non-PDF, unparseable) raise a defined exception (e.g. `DatasheetFetchError`) the management layer catches per-candidate.

### D6 — Per-run extraction cache keyed by `(datasheet_url, frozenset(requested_params))`
A small in-process cache (dict, or `functools.lru_cache` on a normalized key) memoizes `text-fetch + extract` so two survivors sharing a datasheet, or a re-verify, don't refetch/re-run the LLM. Keyed by the URL plus the sorted missing-parameter set, scoped to one `run_pipeline` call.
- *Alternative considered:* reuse `cache.py`. Rejected for now — `cache.py` is a stub owned by `implement-response-cache`; a local memo keeps this change self-contained and is trivially replaceable later.

### D7 — Resilience mirrors `search_and_verify`
One adapter raising, one PDF failing to download, or one extraction erroring never aborts the run: the affected source/candidate is skipped (reported via `on_source` where applicable) and the rest complete. The LLM/`requests` imports stay lazy (inside the enrichment functions) so importing `pipeline` is free and the table-only path needs neither the `llm` extra nor network.

## Risks / Trade-offs

- **LLM cost/latency on large survivor sets** → Gate 1 runs first (cheap, no network), so only survivors are enriched; the per-run cache dedupes shared datasheets; enrichment can be parallelized later if needed.
- **Dropping partials hides "almost-matched, couldn't confirm" parts** → This is the user's chosen policy (return only full matches). The management layer still computes the `partial`/`fail` outcomes internally, so a later flag could re-expose them without redesign.
- **A site row may lack a datasheet link** → then `datasheet_url` is `None`, the candidate's site-missing params cannot be resolved, and Gate 2 drops it. The field defaults to `None`, so adapters that don't set it construct unchanged.
- **LLM extraction can be wrong** → `extract_rf_parameters` forbids guessing (returns `null` when absent) and `to_raw_params` drops ambiguous/unit-missing values, so an unresolved parameter stays `UNKNOWN` → dropped, never a wrongful match. A mis-extracted value could still cause a wrong `FAIL`/`match`; mitigated by the "never guess" contract and `datasheet` confidence labelling.
- **Frozen-dataclass copy churn** → `replace()` allocates a new `Candidate` per enriched survivor; negligible at these result sizes.

## Migration Plan

1. Add `Candidate.datasheet_url: str | None = None` (defaulted — no adapter change required to construct).
2. Add `datasheet_text_from_url` + `DatasheetFetchError` to `datasheet/pdf.py`.
3. Add `rf_finder/pipeline.py` — the management layer — with `run_pipeline` and the enrichment/cache helpers.
4. Point `__main__.py` and `ui/gui.py` at `run_pipeline`; keep `search_and_verify` for the table-only tests.
5. Have each adapter read the datasheet link from its site row into `datasheet_url` (where the site exposes one).

Rollback: revert the call-site switch in step 4; the new module and the defaulted field are inert without callers.

## Open Questions

- Should enrichment fan out concurrently across survivors, or stay sequential for the first cut? (Default: sequential; parallelize if latency warrants.)
- When a datasheet resolves a parameter to a **range/list** whose comparison is `contains`, the existing mapping/verify handle it — but do any requested datasheet-only params need extractor-prompt tuning beyond the current `Temperature`/`MSL`/`length`/`width` coverage? (Track per adapter.)
- Confidence display: this change sets `confidence="datasheet"` on enriched matches but the CLI still does not render confidence (that is `implement-reporter`). Left as-is.
