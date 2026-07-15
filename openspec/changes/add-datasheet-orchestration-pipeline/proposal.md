## Why

Today the search flow is a single pass: `search_and_verify` fetches every adapter's table candidates, verifies each once, and ranks them. A parameter that a listing page does not publish stays `UNKNOWN`, so the candidate can only surface as `partial` — the datasheet is never consulted. The datasheet layer (`rf_finder/datasheet/`: PDF text, LLM extraction, `RawValue` mapping) already exists as building blocks but is **not wired into any flow**, and `Candidate` carries no datasheet link. There is no management layer that sequences retrieve → filter → datasheet-enrich → filter. This change adds that layer so a component is only rejected once we have actually tried to resolve every requested parameter, and the expensive datasheet step runs only on the few candidates worth it.

## What Changes

- Add a **management/orchestration layer** (`rf_finder/pipeline.py`) that runs a two-gate gated pipeline:
  1. **Retrieve** — adapters return table candidates, as today.
  2. **Gate 1 (table filter)** — `verify()` each candidate; drop any that already `FAIL` on a parameter the table provides. Survivors are `match` or `partial`.
  3. **Enrich (datasheet)** — for survivors only, and only for their still-`UNKNOWN` requested parameters, download the datasheet PDF, extract text, run the existing LLM extractor on **only the missing parameters**, map to `RawValue`, and merge into the candidate with `source="datasheet"`.
  4. **Gate 2 (final filter)** — re-verify the enriched candidates and return two result outcomes: **`match`** (every requested parameter `PASS`, site and datasheet) and **`not-verified`** (all site parameters `PASS`, nothing `FAIL`s, but the datasheet could not be accessed to confirm the remaining parameters — and only when at least **80%** of the user's entered parameters are `PASS`). A candidate with any `FAIL`, one left `UNKNOWN` by a datasheet that was read successfully but is silent on the parameter, or a `not-verified` candidate below the 80% coverage threshold, is dropped.
- Reuse `verifier.verify()` as the single comparison engine — the gates are policy over its verdicts, no second comparator.
- Reuse the existing `rf_finder/datasheet` building blocks — no new mapping layer.
- Add an optional `datasheet_url` field to the `Candidate` model; adapters populate it when known. A candidate with no `datasheet_url` cannot be enriched — a "no datasheet access" condition — so, with its site parameters all passing, Gate 2 returns it as `not-verified` rather than dropping it.
- Add a **fetch-datasheet-PDF-from-URL** capability (today `pdf.py` reads local files only).

## Capabilities

### New Capabilities
- `datasheet-orchestration`: the two-gate management pipeline — retrieve, table gate, datasheet enrichment of survivors' unknown parameters, final gate returning only full matches; plus datasheet-PDF-by-URL fetching.

### Modified Capabilities
- `core-data-models`: `Candidate` gains an optional `datasheet_url` field used by the enrichment stage.
- `manufacturer-adapters`: adapters MAY populate `datasheet_url` on the candidates they emit when a per-part datasheet link is available on the source.

## Impact

- **New code**: `rf_finder/pipeline.py` (orchestrator); a datasheet-PDF-by-URL fetch helper in `rf_finder/datasheet/pdf.py`.
- **Modified code**: `rf_finder/models.py` (`Candidate.datasheet_url`); `rf_finder/search.py` / `rf_finder/__main__.py` and `rf_finder/ui/gui.py` call sites switch from `search_and_verify` to the new pipeline (or the pipeline wraps it); adapters optionally set `datasheet_url`.
- **Dependencies**: the datasheet path needs the `llm` extra (`genaifabric`) and network access to fetch PDFs; both are only exercised when enrichment runs, so the table-only path keeps working without them.
- **Behavior change**: results now reflect datasheet-resolved parameters. The result set contains fully verified `match` products plus `not-verified` products (site parameters all pass but the datasheet could not be accessed, and at least 80% of the user's entered parameters pass); plain `partial`/`fail` candidates, and `not-verified` candidates below the 80% coverage threshold, are no longer surfaced. Each returned product exposes product name, manufacturer, datasheet URL, and its `match`/`not-verified` verdict (the internal `source` is not part of the result).
