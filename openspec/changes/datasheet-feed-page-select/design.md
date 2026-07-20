## Context

`extract_rf_parameters` currently sends the whole datasheet text and all
requested parameters to the model in one call. Measurement on ~10 datasheets
across 8 vendors (local provider, `llama3.1:8b` on Ollama) exposed two failures:

- The local provider never sets `num_ctx`, so Ollama's default window applies.
  Measured effective budget is ~2975 tokens once the ~1100-token instruction is
  counted. Whole-text prompts measured ~4.3k–7.2k tokens for 4 of 5 gold
  datasheets, so they were silently truncated and parameters past the cut nulled.
- Requesting several parameters in one call degrades VDD placement. On the exact
  same coherent feed, VDD-only returned `{typ:6, max:6.5}` (correct) while the
  four-parameter request returned `{min:6.5, value:[6]}` (wrong).

The instruction is a weak, global lever (tweaking it for one parameter breaks
another). The feed and the call grouping are strong, local, deterministic levers.

## Goals / Non-Goals

**Goals:**
- Every prompt fits the context window with headroom (no silent truncation).
- VDD typ/max placement is correct and deterministic.
- The reduction generalises across vendors without a per-vendor keyword list.
- The six-field / requested-key output contract is unchanged.

**Non-Goals:**
- Changing the model, provider, or raising `num_ctx`.
- Rewriting the instruction prompt.
- Solving VDD placement from non-tabular prose, or TEMPERATURE column-format
  ranges (recorded as open questions).

## Decisions

**1. VDD feed = page selection, not regex windows.**
VDD needs to see the operating value and the absolute-maximum value *in their
coherent context* to place typ vs max. Measured: ±200-char regex windows
fragment the tables and glue in graph mentions → `{typ:6, value:[5,6]}`; a ±800
window swallows ~82% of the doc → collapse; whole-page feed → `{typ:6, max:6.5}`.
A PDF page is the natural coherent unit, so VDD is fed selected whole pages.

**2. Page selection uses structural signals, not section titles.**
Section titles vary by vendor ("SPECIFICATIONS" vs "Electrical Specifications" vs
"Mechanical Information"). The industry-standard *table structure* is generic: a
Min/Typ/Max column triple marks a spec table; "absolute"/"max rating" marks a
rating table; a supply/drain/bias voltage stated with a value marks a features
page. Selecting on these caught the adca `SPECIFICATIONS` page that a title list
missed, and generalised to all 8 vendors.

**3. A graph-marker (" vs") filter drops chart pages.**
Some vendors (Microchip) repeat a spec header on every page, including charts.
A low " vs" count distinguishes real spec pages from chart pages; the naive
title-substring rule selected 16/21 Microchip pages, the filtered rule 4.

**4. SIZE / MSL / TEMPERATURE = regex locators, not page selection.**
These are self-contained single-value lookups (measured recall 5/5 with regex);
they do not need coherent pages. Keeping them out of page selection removes the
need for a dimension page signal and eliminates a co-location fragility (a
mechanical page being selected only because another signal happened to sit on it).

**5. VDD is extracted in its own call; SIZE/MSL/TEMP grouped.**
Isolating VDD removes the juggling that breaks its placement. The three simple
lookups tolerate grouping (measured correct together), so the cost is 2 calls
per datasheet, not 4.

## Risks / Trade-offs

- **More LLM calls (2 per datasheet) → more CPU time.** → Each call is smaller
  and fits, so per-call latency drops; the VDD-only call measured ~17–140s vs a
  truncated/again wrong single call. Net is acceptable and correct.
- **Page selection depends on PDF pagination.** → Real datasheets are paginated;
  if no page is selected, fall back to the whole text rather than an empty feed.
- **The " vs" threshold and the breadth of the supply-voltage signal are tuned on
  10 datasheets.** → Keep them as named constants; validate on a larger labelled
  corpus before trusting beyond the current set.
- **VDD placement from prose supply statements is still weak** (RWLA1001 placed
  +5V as min, not typ). → Open question; a code-level decode (abs-max section →
  max) is a candidate fallback but out of scope here.

## Open Questions

- VDD placement from non-tabular prose ("Power Supply: +5V" + "Maximum drain
  voltage +7V"): keep as LLM, add a code decode, or a targeted instruction hint?
- TEMPERATURE column-format ranges ("-40 105 °C" with no "to") — regex decode?
- How many pages should the supply-voltage signal select before it over-includes?
- A labelled corpus for precision/recall beyond the current 10 datasheets.
