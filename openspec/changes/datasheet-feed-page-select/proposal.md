## Why

The datasheet parameter extractor feeds the model the **whole datasheet text**
in a **single call for all requested parameters**. Measurement on ~10 datasheets
(8 vendors) showed this is broken two ways:

1. **Silent truncation.** The local provider does not set `num_ctx`, so Ollama's
   default window (effectively ~2975 tokens once the ~1100-token instruction is
   counted) caps the prompt. On 4 of 5 gold datasheets the whole-text prompt
   overflows and is silently truncated — the model never sees the whole document,
   which nulls parameters whose values sit past the cut.
2. **Parameter juggling.** Asking for several parameters in one call degrades the
   hardest one: on the exact same coherent feed, requesting VDD alone yields the
   correct `{typ:6, max:6.5}` while requesting four parameters together yields a
   wrong `{min:6.5, value:[6]}`.

A feed that (a) fits the window and (b) isolates the placement-sensitive
parameter fixes both, deterministically, without touching the fragile prompt.

## What Changes

- **VDD feed = page selection.** Instead of the whole text, VDD is extracted from
  only the coherent PDF pages that carry its data: keep a page when it has a
  Min/Typ/Max table **or** an absolute/max-rating table **or** a supply/drain/bias
  voltage stated with a value, **and** its " vs" graph-marker count is low (drops
  chart pages, including vendors that repeat a spec header on every page).
- **VDD is extracted in its own isolated call** (one requested parameter) to avoid
  juggling — validated to restore correct typ/max placement.
- **SIZE / MSL / TEMPERATURE feed = regex locators.** These are self-contained
  lookups; they are located with ±window regex (A×B dimension incl. inch / mils /
  diameter, MSL keyword, operating/storage temperature) and extracted together in
  one grouped call.
- **Feeds are page/region subsets, not the whole document** — every prompt now
  fits the context window with headroom (measured ~1.6k–3.4k tokens vs the
  overflowing ~4.3k–7.2k).
- No change to the six-field output contract or the requested-key contract.

## Capabilities

### New Capabilities
- `datasheet-extraction-feed`: how the datasheet is reduced to what the model
  sees — page selection for placement-sensitive parameters, regex-locator windows
  for self-contained parameters, and the per-parameter call grouping — so every
  prompt fits the context window and placement stays correct.

### Modified Capabilities
<!-- The base datasheet-extraction behaviour is still an in-flight change
     (add-datasheet-extraction / robust-param-extraction), not yet in
     openspec/specs/, so there is no archived capability to file a delta against. -->

## Impact

- `rf_finder/datasheet/extractor.py`: `extract_rf_parameters` gains a feed step
  (page selection / regex locators) and a per-parameter call split; the extraction
  contract and normalisation are unchanged.
- `rf_finder/datasheet/pdf.py`: needs per-page access (already supports
  `pages=[...]`), plus a page-text accessor for the selector.
- Interacts with the in-flight `robust-param-extraction` work (VDD alias hints,
  MSL/SIZE grounding) — those code levers remain; this changes only the feed.
- Open questions carried forward (not solved here): VDD placement from
  non-tabular prose supply statements, TEMPERATURE column-format ranges
  ("-40 105 °C" with no "to"), tuning how many pages the voltage signal selects,
  and validation on a larger labelled corpus.
