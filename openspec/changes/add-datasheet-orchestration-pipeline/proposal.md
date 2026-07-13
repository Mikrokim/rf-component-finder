## Why

Today the search flow is a single pass: `search_and_verify` fetches every adapter's table candidates, verifies each once, and ranks them. A parameter that a listing page does not publish stays `UNKNOWN`, so the candidate can only surface as `partial` — the datasheet is never consulted. The datasheet layer (`rf_finder/datasheet/`: PDF text, LLM extraction, `RawValue` mapping) already exists as building blocks but is **not wired into any flow**, and `Candidate` carries no datasheet link. There is no management layer that sequences retrieve → filter → datasheet-enrich → filter. This change adds that layer so a component is only rejected once we have actually tried to resolve every requested parameter, and the expensive datasheet step runs only on the few candidates worth it.

## What Changes

- Add a **management/orchestration layer** (`rf_finder/pipeline.py`) that runs a two-gate gated pipeline:
  1. **Retrieve** — adapters return table candidates, as today.
  2. **Gate 1 (table filter)** — `verify()` each candidate; drop any that already `FAIL` on a parameter the table provides. Survivors are `match` or `partial`.
  3. **Enrich (datasheet)** — for survivors only, and only for their still-`UNKNOWN` requested parameters, download the datasheet PDF, extract text, run the existing LLM extractor on **only the missing parameters**, map to `RawValue`, and merge into the candidate with `source="datasheet"`.
  4. **Gate 2 (final filter)** — re-verify the enriched candidates and return **only full matches** (`overall == "match"`). `FAIL` and `partial` are dropped.
- Reuse `verifier.verify()` as the single comparison engine — the gates are policy over its verdicts, no second comparator.
- Reuse the existing `rf_finder/datasheet` building blocks — no new mapping layer.
- Add an optional `datasheet_url` field to the `Candidate` model; adapters populate it when known. A candidate with no `datasheet_url` cannot be enriched, so its `UNKNOWN` params remain and it is dropped by Gate 2.
- Add a **fetch-datasheet-PDF-from-URL** capability (today `pdf.py` reads local files only).
- Add **caching of datasheet extraction** so a repeated part/parameter set does not re-download or re-run the LLM within a run.

## Capabilities

### New Capabilities
- `datasheet-orchestration`: the two-gate management pipeline — retrieve, table gate, datasheet enrichment of survivors' unknown parameters, final gate returning only full matches; plus datasheet-PDF-by-URL fetching and extraction caching.

### Modified Capabilities
- `core-data-models`: `Candidate` gains an optional `datasheet_url` field used by the enrichment stage.
- `manufacturer-adapters`: adapters MAY populate `datasheet_url` on the candidates they emit when a per-part datasheet link is available on the source.

## Impact

- **New code**: `rf_finder/pipeline.py` (orchestrator); a datasheet-PDF-by-URL fetch helper in `rf_finder/datasheet/pdf.py`; an extraction cache.
- **Modified code**: `rf_finder/models.py` (`Candidate.datasheet_url`); `rf_finder/search.py` / `rf_finder/__main__.py` and `rf_finder/ui/gui.py` call sites switch from `search_and_verify` to the new pipeline (or the pipeline wraps it); adapters optionally set `datasheet_url`.
- **Dependencies**: the datasheet path needs the `llm` extra (`genaifabric`) and network access to fetch PDFs; both are only exercised when enrichment runs, so the table-only path keeps working without them.
- **Behavior change**: results now reflect datasheet-resolved parameters, and the default result set is only full matches (partials are no longer surfaced as results).
